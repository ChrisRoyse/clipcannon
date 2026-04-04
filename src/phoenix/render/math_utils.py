"""GPU math utilities for Gaussian Splatting avatar rendering.

Provides TBN frame computation, quaternion ops, and other
3D math primitives used by the avatar pipeline.
"""

from __future__ import annotations

import torch
import torch.nn.functional as Fn


def compute_face_tbn(
    tri_verts: torch.Tensor,
    face_uvs: torch.Tensor,
) -> torch.Tensor:
    """Compute tangent-bitangent-normal frames for mesh triangles.

    Args:
        tri_verts: (B, F, 3, 3) triangle vertex positions.
        face_uvs: (F, 3, 2) per-face UV coordinates.

    Returns:
        (B, F, 3, 3) TBN rotation matrices.
    """
    # Edge vectors
    e1 = tri_verts[:, :, 1] - tri_verts[:, :, 0]  # (B, F, 3)
    e2 = tri_verts[:, :, 2] - tri_verts[:, :, 0]  # (B, F, 3)

    # UV deltas
    duv1 = face_uvs[:, 1] - face_uvs[:, 0]  # (F, 2)
    duv2 = face_uvs[:, 2] - face_uvs[:, 0]  # (F, 2)

    # Normal
    normal = torch.cross(e1, e2, dim=-1)
    normal = Fn.normalize(normal, dim=-1)

    # Tangent and bitangent from UV mapping
    det = duv1[:, 0] * duv2[:, 1] - duv1[:, 1] * duv2[:, 0]
    det = det.unsqueeze(0).unsqueeze(-1).clamp(min=1e-8)

    tangent = (duv2[:, 1:2].unsqueeze(0) * e1 - duv1[:, 1:2].unsqueeze(0) * e2) / det
    tangent = Fn.normalize(tangent, dim=-1)

    bitangent = torch.cross(normal, tangent, dim=-1)
    bitangent = Fn.normalize(bitangent, dim=-1)

    # Stack into rotation matrix: columns are T, B, N
    tbn = torch.stack([tangent, bitangent, normal], dim=-1)  # (B, F, 3, 3)
    return tbn


def matrix_to_quaternion(matrix: torch.Tensor) -> torch.Tensor:
    """Convert 3x3 rotation matrix to quaternion (w, x, y, z).

    Args:
        matrix: (..., 3, 3) rotation matrices.

    Returns:
        (..., 4) quaternions.
    """
    if matrix.shape[-2:] != (3, 3):
        raise ValueError(f"Expected 3x3 matrix, got {matrix.shape}")

    batch_shape = matrix.shape[:-2]
    m = matrix.reshape(-1, 3, 3)
    B = m.shape[0]

    trace = m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2]

    qw = torch.zeros(B, device=m.device, dtype=m.dtype)
    qx = torch.zeros_like(qw)
    qy = torch.zeros_like(qw)
    qz = torch.zeros_like(qw)

    # Case 1: trace > 0
    mask = trace > 0
    s = torch.sqrt(trace[mask] + 1.0) * 2
    qw[mask] = 0.25 * s
    qx[mask] = (m[mask, 2, 1] - m[mask, 1, 2]) / s
    qy[mask] = (m[mask, 0, 2] - m[mask, 2, 0]) / s
    qz[mask] = (m[mask, 1, 0] - m[mask, 0, 1]) / s

    # Case 2: m00 is max diagonal
    mask2 = (~mask) & (m[:, 0, 0] > m[:, 1, 1]) & (m[:, 0, 0] > m[:, 2, 2])
    s2 = torch.sqrt(1.0 + m[mask2, 0, 0] - m[mask2, 1, 1] - m[mask2, 2, 2]) * 2
    qw[mask2] = (m[mask2, 2, 1] - m[mask2, 1, 2]) / s2
    qx[mask2] = 0.25 * s2
    qy[mask2] = (m[mask2, 0, 1] + m[mask2, 1, 0]) / s2
    qz[mask2] = (m[mask2, 0, 2] + m[mask2, 2, 0]) / s2

    # Case 3: m11 is max diagonal
    mask3 = (~mask) & (~mask2) & (m[:, 1, 1] > m[:, 2, 2])
    s3 = torch.sqrt(1.0 + m[mask3, 1, 1] - m[mask3, 0, 0] - m[mask3, 2, 2]) * 2
    qw[mask3] = (m[mask3, 0, 2] - m[mask3, 2, 0]) / s3
    qx[mask3] = (m[mask3, 0, 1] + m[mask3, 1, 0]) / s3
    qy[mask3] = 0.25 * s3
    qz[mask3] = (m[mask3, 1, 2] + m[mask3, 2, 1]) / s3

    # Case 4: m22 is max diagonal
    mask4 = (~mask) & (~mask2) & (~mask3)
    s4 = torch.sqrt(1.0 + m[mask4, 2, 2] - m[mask4, 0, 0] - m[mask4, 1, 1]) * 2
    qw[mask4] = (m[mask4, 1, 0] - m[mask4, 0, 1]) / s4
    qx[mask4] = (m[mask4, 0, 2] + m[mask4, 2, 0]) / s4
    qy[mask4] = (m[mask4, 1, 2] + m[mask4, 2, 1]) / s4
    qz[mask4] = 0.25 * s4

    q = torch.stack([qw, qx, qy, qz], dim=-1)
    q = Fn.normalize(q, dim=-1)
    return q.reshape(*batch_shape, 4)


def quaternion_multiply(q1: torch.Tensor, q2: torch.Tensor) -> torch.Tensor:
    """Hamilton product of two quaternion tensors (w, x, y, z format).

    Args:
        q1: (..., 4) first quaternion.
        q2: (..., 4) second quaternion.

    Returns:
        (..., 4) product quaternion.
    """
    w1, x1, y1, z1 = q1.unbind(-1)
    w2, x2, y2, z2 = q2.unbind(-1)

    return torch.stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ], dim=-1)
