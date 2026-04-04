"""Low-level CuPy CUDA kernels and color conversion helpers.

Contains raw CUDA kernel definitions and internal YUV420 conversion
routines used by the compositor. Not part of the public API.
"""

from __future__ import annotations

import cupy as cp

from phoenix.errors import CompositorError

# ---------------------------------------------------------------------------
# CuPy raw kernels — compiled once, cached by CuPy
# ---------------------------------------------------------------------------

BILINEAR_RESIZE_KERNEL = cp.RawKernel(
    r"""
extern "C" __global__
void bilinear_resize(
    const float* __restrict__ src,
    float* __restrict__ dst,
    int src_h, int src_w,
    int dst_h, int dst_w,
    int channels
) {
    int idx = blockDim.x * blockIdx.x + threadIdx.x;
    int total = dst_h * dst_w * channels;
    if (idx >= total) return;

    int c = idx % channels;
    int x_dst = (idx / channels) % dst_w;
    int y_dst = (idx / channels) / dst_w;

    float scale_y = (float)src_h / (float)dst_h;
    float scale_x = (float)src_w / (float)dst_w;

    float y_src = ((float)y_dst + 0.5f) * scale_y - 0.5f;
    float x_src = ((float)x_dst + 0.5f) * scale_x - 0.5f;

    int y0 = (int)floorf(y_src);
    int x0 = (int)floorf(x_src);
    int y1 = y0 + 1;
    int x1 = x0 + 1;

    // Clamp
    y0 = max(0, min(y0, src_h - 1));
    y1 = max(0, min(y1, src_h - 1));
    x0 = max(0, min(x0, src_w - 1));
    x1 = max(0, min(x1, src_w - 1));

    float fy = y_src - floorf(y_src);
    float fx = x_src - floorf(x_src);

    float v00 = src[(y0 * src_w + x0) * channels + c];
    float v01 = src[(y0 * src_w + x1) * channels + c];
    float v10 = src[(y1 * src_w + x0) * channels + c];
    float v11 = src[(y1 * src_w + x1) * channels + c];

    float val = (1.0f - fy) * ((1.0f - fx) * v00 + fx * v01)
              + fy          * ((1.0f - fx) * v10 + fx * v11);

    dst[idx] = val;
}
""",
    "bilinear_resize",
)

ALPHA_BLEND_KERNEL = cp.RawKernel(
    r"""
extern "C" __global__
void alpha_blend(
    const float* __restrict__ fg,
    const float* __restrict__ bg,
    const float* __restrict__ alpha,
    float* __restrict__ out,
    int height, int width, int channels,
    int alpha_channels
) {
    int idx = blockDim.x * blockIdx.x + threadIdx.x;
    int total = height * width * channels;
    if (idx >= total) return;

    int c = idx % channels;
    int pixel = idx / channels;

    // alpha may be (H, W, 1) or (H, W, 3) or (H, W)
    float a;
    if (alpha_channels == 1) {
        a = alpha[pixel];
    } else {
        a = alpha[pixel * alpha_channels + min(c, alpha_channels - 1)];
    }

    out[idx] = fg[idx] * a + bg[idx] * (1.0f - a);
}
""",
    "alpha_blend",
)


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_gpu_array(arr: cp.ndarray, name: str) -> None:
    """Validate that an array is a CuPy GPU array with float32 dtype.

    Args:
        arr: Array to validate.
        name: Parameter name for error messages.

    Raises:
        CompositorError: If validation fails.
    """
    if not isinstance(arr, cp.ndarray):
        raise CompositorError(
            f"{name} must be a CuPy ndarray, got {type(arr).__name__}",
            context={"type": type(arr).__name__},
        )
    if arr.dtype != cp.float32:
        raise CompositorError(
            f"{name} must be float32, got {arr.dtype}",
            context={"dtype": str(arr.dtype), "name": name},
        )


# ---------------------------------------------------------------------------
# YUV420 color conversion helpers
# ---------------------------------------------------------------------------


def rgb_to_yuv420(image: cp.ndarray) -> cp.ndarray:
    """Convert RGB float32 (H, W, 3) to YUV420 planar on GPU.

    Output layout: Y plane (H, W) followed by interleaved UV plane
    (H//2, W) with U on even columns, V on odd columns.

    Args:
        image: GPU array, float32, shape (H, W, 3), range [0, 1].

    Returns:
        YUV420 GPU array, float32, shape (H * 3 // 2, W).

    Raises:
        CompositorError: If dimensions are not even.
    """
    h, w, _ = image.shape
    if h % 2 != 0 or w % 2 != 0:
        raise CompositorError(
            "RGB->YUV420 requires even dimensions",
            context={"height": h, "width": w},
        )

    r = image[:, :, 0]
    g = image[:, :, 1]
    b = image[:, :, 2]

    # BT.601 conversion
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u_full = -0.14713 * r - 0.28886 * g + 0.436 * b + 0.5
    v_full = 0.615 * r - 0.51499 * g - 0.10001 * b + 0.5

    # Subsample U and V by 2x2 averaging
    u = (
        u_full[0::2, 0::2]
        + u_full[0::2, 1::2]
        + u_full[1::2, 0::2]
        + u_full[1::2, 1::2]
    ) * 0.25
    v = (
        v_full[0::2, 0::2]
        + v_full[0::2, 1::2]
        + v_full[1::2, 0::2]
        + v_full[1::2, 1::2]
    ) * 0.25

    # Pack into planar layout: Y then interleaved UV (NV12-like)
    out = cp.empty((h * 3 // 2, w), dtype=cp.float32)
    out[:h, :] = y

    half_h = h // 2
    uv_plane = out[h:, :]
    uv_plane[:half_h, 0::2] = u
    uv_plane[:half_h, 1::2] = v

    return out


# ---------------------------------------------------------------------------
# Fused BGR uint8 -> NV12 uint8 kernel (single-pass, one thread per 2x2)
# ---------------------------------------------------------------------------

_BGR_TO_NV12_KERNEL = cp.RawKernel(
    r"""
extern "C" __global__
void bgr_to_nv12(
    const unsigned char* __restrict__ bgr,
    unsigned char* __restrict__ nv12,
    int height, int width
) {
    // Each thread processes a 2x2 pixel block
    int bx = (blockDim.x * blockIdx.x + threadIdx.x);
    int by = (blockDim.y * blockIdx.y + threadIdx.y);

    int half_w = width / 2;
    int half_h = height / 2;
    if (bx >= half_w || by >= half_h) return;

    int x = bx * 2;
    int y = by * 2;

    // Read 4 BGR pixels (row-major, channels=3)
    int stride = width * 3;
    int nv12_stride = width;

    float r00, g00, b00, r01, g01, b01;
    float r10, g10, b10, r11, g11, b11;

    int idx00 = y * stride + x * 3;
    b00 = (float)bgr[idx00];
    g00 = (float)bgr[idx00 + 1];
    r00 = (float)bgr[idx00 + 2];

    int idx01 = y * stride + (x + 1) * 3;
    b01 = (float)bgr[idx01];
    g01 = (float)bgr[idx01 + 1];
    r01 = (float)bgr[idx01 + 2];

    int idx10 = (y + 1) * stride + x * 3;
    b10 = (float)bgr[idx10];
    g10 = (float)bgr[idx10 + 1];
    r10 = (float)bgr[idx10 + 2];

    int idx11 = (y + 1) * stride + (x + 1) * 3;
    b11 = (float)bgr[idx11];
    g11 = (float)bgr[idx11 + 1];
    r11 = (float)bgr[idx11 + 2];

    // BT.601 RGB->YUV
    float y00 =  0.299f * r00 + 0.587f * g00 + 0.114f * b00;
    float y01 =  0.299f * r01 + 0.587f * g01 + 0.114f * b01;
    float y10 =  0.299f * r10 + 0.587f * g10 + 0.114f * b10;
    float y11 =  0.299f * r11 + 0.587f * g11 + 0.114f * b11;

    // Write Y plane
    nv12[y * nv12_stride + x]           = (unsigned char)min(max(y00, 0.0f), 255.0f);
    nv12[y * nv12_stride + x + 1]       = (unsigned char)min(max(y01, 0.0f), 255.0f);
    nv12[(y + 1) * nv12_stride + x]     = (unsigned char)min(max(y10, 0.0f), 255.0f);
    nv12[(y + 1) * nv12_stride + x + 1] = (unsigned char)min(max(y11, 0.0f), 255.0f);

    // Average RGB across the 2x2 block for chroma
    float r_avg = (r00 + r01 + r10 + r11) * 0.25f;
    float g_avg = (g00 + g01 + g10 + g11) * 0.25f;
    float b_avg = (b00 + b01 + b10 + b11) * 0.25f;

    float u = -0.14713f * r_avg - 0.28886f * g_avg + 0.436f * b_avg + 128.0f;
    float v =  0.615f   * r_avg - 0.51499f * g_avg - 0.10001f * b_avg + 128.0f;

    // Write UV plane (interleaved NV12: U on even cols, V on odd cols)
    int uv_row = height + by;
    nv12[uv_row * nv12_stride + x]     = (unsigned char)min(max(u, 0.0f), 255.0f);
    nv12[uv_row * nv12_stride + x + 1] = (unsigned char)min(max(v, 0.0f), 255.0f);
}
""",
    "bgr_to_nv12",
)


def bgr_to_nv12_gpu(bgr: cp.ndarray) -> cp.ndarray:
    """Convert BGR uint8 (H, W, 3) on GPU to NV12 uint8 (H*3//2, W).

    Uses a fused CUDA kernel: one thread per 2x2 pixel block computes
    4 luma values and 1 chroma pair. No intermediate float32 buffers.

    Args:
        bgr: CuPy uint8 array, shape (H, W, 3), BGR channel order.

    Returns:
        NV12 CuPy uint8 array, shape (H*3//2, W). Y plane in rows
        0..H-1, interleaved UV in rows H..H*3//2-1.

    Raises:
        CompositorError: If dimensions are not even or input is invalid.
    """
    if not isinstance(bgr, cp.ndarray):
        raise CompositorError(
            "bgr must be a CuPy ndarray",
            context={"type": type(bgr).__name__},
        )
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise CompositorError(
            "bgr must have shape (H, W, 3)",
            context={"shape": str(bgr.shape)},
        )
    if bgr.dtype != cp.uint8:
        raise CompositorError(
            "bgr must be uint8",
            context={"dtype": str(bgr.dtype)},
        )

    h, w, _ = bgr.shape
    if h % 2 != 0 or w % 2 != 0:
        raise CompositorError(
            "BGR->NV12 requires even dimensions",
            context={"height": h, "width": w},
        )
    if h == 0 or w == 0:
        raise CompositorError(
            "BGR frame has zero size",
            context={"height": h, "width": w},
        )

    nv12 = cp.empty((h * 3 // 2, w), dtype=cp.uint8)

    half_w = w // 2
    half_h = h // 2
    block = (16, 16)
    grid = (
        (half_w + block[0] - 1) // block[0],
        (half_h + block[1] - 1) // block[1],
    )

    bgr_contig = cp.ascontiguousarray(bgr)
    _BGR_TO_NV12_KERNEL(grid, block, (bgr_contig, nv12, h, w))

    return nv12


def yuv420_to_rgb(image: cp.ndarray) -> cp.ndarray:
    """Convert YUV420 planar to RGB float32 on GPU.

    Expects layout produced by rgb_to_yuv420: Y plane (H, W) then
    interleaved UV (H//2, W) with U on even cols, V on odd cols.

    Args:
        image: GPU array, float32, shape (H * 3 // 2, W).

    Returns:
        RGB GPU array, float32, shape (H, W, 3).

    Raises:
        CompositorError: If derived dimensions are not even.
    """
    total_h, w = image.shape
    h = total_h * 2 // 3

    if h % 2 != 0 or w % 2 != 0:
        raise CompositorError(
            "YUV420->RGB requires even dimensions",
            context={"derived_h": h, "width": w},
        )

    y = image[:h, :]

    half_h = h // 2
    uv_plane = image[h : h + half_h, :]
    u_sub = uv_plane[:, 0::2]
    v_sub = uv_plane[:, 1::2]

    # Upsample U and V to full resolution by nearest-neighbor repeat
    u = cp.repeat(cp.repeat(u_sub, 2, axis=0), 2, axis=1)
    v = cp.repeat(cp.repeat(v_sub, 2, axis=0), 2, axis=1)

    # Trim if repeat overshot
    u = u[:h, :w]
    v = v[:h, :w]

    # Undo BT.601 offset
    u = u - 0.5
    v = v - 0.5

    # BT.601 inverse
    r = y + 1.13983 * v
    g = y - 0.39465 * u - 0.58060 * v
    b = y + 2.03211 * u

    rgb = cp.stack([r, g, b], axis=2)
    return cp.clip(rgb, 0.0, 1.0)
