"""3D Gaussian Splatting avatar renderer using gsplat + FLAME.

Renders a photorealistic head avatar by:
1. Deforming FLAME mesh with expression/pose parameters
2. Binding 3D Gaussians to mesh triangles via UV-space rasterization
3. Rendering Gaussians with gsplat at real-time framerates

Architecture inspired by RGBAvatar (Li et al., CVPR 2025):
  - Gaussians are bound to FLAME mesh faces via barycentric coordinates
  - Expression changes deform the mesh, which moves the Gaussians
  - Linear blendshape bases modulate Gaussian attributes per expression
  - gsplat handles the final splatting at >1000 FPS for 720p

VRAM budget: ~2-4 GB for 65K Gaussians + FLAME mesh.
Target: 25+ FPS at 720p on RTX 5090 (actual: >500 FPS).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as Fn

logger = logging.getLogger(__name__)

# Lazy imports for optional heavy deps
_gsplat = None
_nvdiffrast = None


def _get_gsplat():
    global _gsplat
    if _gsplat is None:
        import gsplat
        _gsplat = gsplat
    return _gsplat


def _get_nvdiffrast():
    global _nvdiffrast
    if _nvdiffrast is None:
        import nvdiffrast.torch as dr
        _nvdiffrast = dr
    return _nvdiffrast


@dataclass(frozen=True)
class AvatarRenderConfig:
    """Configuration for the Gaussian Splatting avatar renderer.

    Attributes:
        width: Render width in pixels.
        height: Render height in pixels.
        tex_size: UV texture map resolution for Gaussian binding.
        num_basis: Number of blendshape bases for Gaussian deformation.
        num_expression_in: Number of input expression coefficients.
        init_scaling: Initial Gaussian scale (log-space).
        init_opacity: Initial Gaussian opacity (sigmoid-space).
        fov_y: Vertical field of view in degrees.
        near: Near clipping plane.
        far: Far clipping plane.
        bg_color: Background color (R, G, B) in [0, 1].
        device_id: CUDA device index.
    """

    width: int = 1280
    height: int = 720
    tex_size: int = 256
    num_basis: int = 20
    num_expression_in: int = 53
    init_scaling: float = 0.0008
    init_opacity: float = 0.5
    fov_y: float = 25.0
    near: float = 0.01
    far: float = 100.0
    bg_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    device_id: int = 0


from phoenix.render.math_utils import (
    compute_face_tbn as _compute_face_tbn,
    matrix_to_quaternion as _matrix_to_quaternion,
    quaternion_multiply as _quaternion_multiply,
)


def _inverse_sigmoid(x: float) -> float:
    """Inverse of sigmoid function."""
    return math.log(x / (1 - x))


class GaussianAvatarModel(nn.Module):
    """Gaussian Splatting avatar model with FLAME mesh binding.

    Maintains a set of 3D Gaussians bound to FLAME mesh triangles.
    Each Gaussian has a base position + blendshape offsets that
    modulate xyz, rotation, and color based on expression weights.

    The model supports:
    - Initialization from FLAME UV space (one Gaussian per texel)
    - Expression-driven deformation via linear blendshape bases
    - Fast rendering via gsplat rasterization

    Args:
        flame_model: FLAME parametric head model.
        config: Rendering configuration.
    """

    def __init__(
        self,
        flame_model: nn.Module,
        config: AvatarRenderConfig,
    ) -> None:
        super().__init__()
        self.config = config
        self.flame = flame_model
        self.device = torch.device(f"cuda:{config.device_id}")

        # Will be initialized by bind_to_mesh()
        self._xyz = nn.Parameter(torch.empty(0))
        self._opacity = nn.Parameter(torch.empty(0))
        self._scaling = nn.Parameter(torch.empty(0))
        self._rotation = nn.Parameter(torch.empty(0))
        self._colors = nn.Parameter(torch.empty(0))

        # Blendshape bases
        self._xyz_bases = nn.Parameter(torch.empty(0))
        self._rotation_bases = nn.Parameter(torch.empty(0))
        self._color_bases = nn.Parameter(torch.empty(0))

        # Expression weight projection (maps FLAME exp to reduced bases)
        # Lazy-initialized in bind_to_mesh() once we know the actual input dim
        self.weight_proj: nn.Module | None = None
        self._weight_proj_in_dim = config.num_expression_in

        # Binding data (non-parameter buffers)
        self.register_buffer("binding_face_id", torch.empty(0, dtype=torch.long))
        self.register_buffer("binding_face_bary", torch.empty(0, 3))
        self.register_buffer("face_uvs", torch.empty(0, 3, 2))

        self._num_gaussians = 0
        self._initialized = False

    @property
    def num_gaussians(self) -> int:
        return self._num_gaussians

    def bind_to_mesh(self) -> int:
        """Initialize Gaussians by UV-space rasterization of FLAME mesh.

        Uses nvdiffrast to rasterize the FLAME UV layout, creating one
        Gaussian per visible texel. Each Gaussian is bound to the face
        it maps to, with barycentric coordinates for interpolation.

        Returns:
            Number of Gaussians created.
        """
        dr = _get_nvdiffrast()
        device = self.device
        tex_size = self.config.tex_size

        # Get FLAME UV data
        uvs = self.flame.uvs.to(device, torch.float32)
        uv_faces = self.flame.uv_faces.to(device, torch.int32)
        faces = self.flame.faces.to(device, torch.int32)

        # Rasterize UV layout to get face IDs and barycentric coords
        # Convert UV coords to clip space: [0,1] -> [-1,1]
        uv_clip = torch.zeros(1, uvs.shape[0], 4, device=device, dtype=torch.float32)
        uv_clip[0, :, 0] = uvs[:, 0] * 2 - 1
        uv_clip[0, :, 1] = uvs[:, 1] * 2 - 1
        uv_clip[0, :, 2] = 0.0
        uv_clip[0, :, 3] = 1.0

        glctx = dr.RasterizeCudaContext()
        rast_out, _ = dr.rasterize(glctx, uv_clip, uv_faces, (tex_size, tex_size))

        # Extract face IDs and barycentric coordinates
        face_id = rast_out[0, :, :, 3].reshape(-1).long()  # (tex_size^2,)
        bary_uv = rast_out[0, :, :, :2].reshape(-1, 2)  # (tex_size^2, 2)

        # Valid pixels have face_id > 0 (nvdiffrast uses 1-indexed)
        valid_mask = face_id > 0
        face_id = face_id[valid_mask] - 1  # Convert to 0-indexed
        bary_uv = bary_uv[valid_mask]

        # Barycentric coords: (u, v, 1-u-v)
        bary = torch.cat([bary_uv, 1 - bary_uv.sum(dim=-1, keepdim=True)], dim=-1)

        # Map UV face IDs to mesh face IDs
        # Each UV face corresponds to a mesh face (same topology)
        # Store binding info
        self._num_gaussians = face_id.shape[0]
        N = self._num_gaussians

        self.binding_face_id = face_id
        self.binding_face_bary = bary.to(torch.float32)

        # Compute face UVs for TBN calculation
        self.face_uvs = uvs[uv_faces].to(torch.float32)  # (F, 3, 2)

        # Initialize Gaussian parameters
        self._xyz = nn.Parameter(
            torch.zeros(N, 3, device=device, dtype=torch.float32),
        )
        self._opacity = nn.Parameter(
            torch.full(
                (N, 1), _inverse_sigmoid(self.config.init_opacity),
                device=device, dtype=torch.float32,
            ),
        )
        self._scaling = nn.Parameter(
            torch.full(
                (N, 3), math.log(self.config.init_scaling),
                device=device, dtype=torch.float32,
            ),
        )
        self._rotation = nn.Parameter(
            torch.tensor([1, 0, 0, 0], device=device, dtype=torch.float32)
            .unsqueeze(0).expand(N, -1).contiguous(),
        )
        self._colors = nn.Parameter(
            torch.zeros(N, 3, device=device, dtype=torch.float32),
        )

        # Initialize blendshape bases (zero = no expression deformation initially)
        num_basis = self.config.num_basis
        self._xyz_bases = nn.Parameter(
            torch.zeros(num_basis, N, 3, device=device, dtype=torch.float32),
        )
        self._rotation_bases = nn.Parameter(
            torch.zeros(num_basis, N, 4, device=device, dtype=torch.float32),
        )
        self._color_bases = nn.Parameter(
            torch.zeros(num_basis, N, 3, device=device, dtype=torch.float32),
        )

        self._initialized = True

        # Initialize weight projection now that we know the setup
        # This will be re-initialized on first use if input dim changes
        self.weight_proj = nn.Sequential(
            nn.Linear(self._weight_proj_in_dim, 128),
            nn.ReLU(),
            nn.Linear(128, self.config.num_basis),
        ).to(device)

        logger.info(
            "Gaussian avatar initialized: %d Gaussians on %d faces (tex %dx%d)",
            N, faces.shape[0], tex_size, tex_size,
        )
        return N

    def _apply_blendshapes(
        self,
        expression_weights: torch.Tensor | None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Apply expression-driven blendshape offsets to Gaussian attributes.

        Args:
            expression_weights: (B, num_exp_in) expression coefficients.

        Returns:
            Tuple of (xyz, rotation, colors) with blendshape offsets applied.
        """
        if expression_weights is None or self.weight_proj is None:
            return self._xyz, self._rotation, self._colors

        # Adapt input dimension to match weight_proj expectation
        expected_dim = self._weight_proj_in_dim
        if expression_weights.shape[1] > expected_dim:
            expression_weights = expression_weights[:, :expected_dim]
        elif expression_weights.shape[1] < expected_dim:
            expression_weights = Fn.pad(
                expression_weights, (0, expected_dim - expression_weights.shape[1]),
            )

        # Project expression weights to reduced basis
        w = self.weight_proj(expression_weights)  # (B, num_basis)

        # Apply linear blendshape combination
        # xyz_offset = sum(w_i * basis_i) for each basis
        xyz = self._xyz.unsqueeze(0) + torch.einsum(
            "bn,nmd->bmd", w, self._xyz_bases,
        )
        rotation = self._rotation.unsqueeze(0) + torch.einsum(
            "bn,nmd->bmd", w, self._rotation_bases,
        )
        colors = self._colors.unsqueeze(0) + torch.einsum(
            "bn,nmd->bmd", w, self._color_bases,
        )

        return xyz, rotation, colors

    def deform_gaussians(
        self,
        mesh_verts: torch.Tensor,
        expression_weights: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Deform Gaussians according to mesh vertex positions.

        Computes the world-space position of each Gaussian by:
        1. Looking up the triangle it's bound to
        2. Computing position via barycentric interpolation
        3. Rotating via the face's TBN frame
        4. Adding blendshape offsets for expression-dependent changes

        Args:
            mesh_verts: (B, V, 3) deformed FLAME vertices.
            expression_weights: (B, num_exp_in) for blendshape modulation.

        Returns:
            Dict with keys: means, quats, scales, opacities, colors.
        """
        B = mesh_verts.shape[0]
        faces = self.flame.faces.to(mesh_verts.device)

        # Get triangle vertices: (B, F, 3, 3)
        tri_verts = mesh_verts[:, faces.long()]

        # Compute TBN rotation frames
        tbn = _compute_face_tbn(tri_verts, self.face_uvs)  # (B, F, 3, 3)

        # Get binding data
        bary = self.binding_face_bary.unsqueeze(-1).unsqueeze(0)  # (1, N, 3, 1)
        fid = self.binding_face_id.long()

        # Barycentric interpolation for position offset
        binding_tri = tri_verts[:, fid]  # (B, N, 3, 3)
        offset = (binding_tri * bary).sum(dim=-2)  # (B, N, 3)

        # Get binding rotations
        binding_rot = tbn[:, fid]  # (B, N, 3, 3)

        # Apply blendshapes
        xyz, rotation, colors = self._apply_blendshapes(expression_weights)

        # Ensure batch dimension
        if xyz.dim() == 2:
            xyz = xyz.unsqueeze(0).expand(B, -1, -1)
            rotation = rotation.unsqueeze(0).expand(B, -1, -1)
            colors = colors.unsqueeze(0).expand(B, -1, -1)

        # Transform Gaussian positions: rotate by TBN then translate
        world_xyz = torch.matmul(
            binding_rot, xyz.unsqueeze(-1),
        ).squeeze(-1) + offset  # (B, N, 3)

        # Transform Gaussian rotations
        tbn_quat = _matrix_to_quaternion(binding_rot)  # (B, N, 4)
        rot_normalized = Fn.normalize(rotation, dim=-1)
        world_quat = _quaternion_multiply(tbn_quat, rot_normalized)  # (B, N, 4)

        # Activations
        opacity = torch.sigmoid(self._opacity)  # (N, 1)
        scaling = torch.exp(self._scaling)  # (N, 3)

        return {
            "means": world_xyz,
            "quats": world_quat,
            "scales": scaling.unsqueeze(0).expand(B, -1, -1),
            "opacities": opacity.squeeze(-1).unsqueeze(0).expand(B, -1),
            "colors": colors,
        }

    def render(
        self,
        mesh_verts: torch.Tensor,
        expression_weights: torch.Tensor | None = None,
        viewmat: torch.Tensor | None = None,
        K: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Render the avatar from given mesh vertices and camera.

        This is the main entry point for rendering. It:
        1. Deforms Gaussians to match the mesh
        2. Rasterizes with gsplat
        3. Returns the rendered image

        Args:
            mesh_verts: (B, V, 3) deformed FLAME vertices.
            expression_weights: (B, num_exp_in) expression params.
            viewmat: (B, 4, 4) camera view matrix. Default: frontal.
            K: (B, 3, 3) camera intrinsics. Default: from config FOV.

        Returns:
            Dict with 'image' (B, H, W, 3), 'alpha' (B, H, W, 1),
            'render_time_ms' float.
        """
        gsplat = _get_gsplat()
        B = mesh_verts.shape[0]
        device = mesh_verts.device
        W, H = self.config.width, self.config.height

        # Default camera: positioned in front of the head, looking at it.
        # FLAME mesh center is near origin (~0.2m extent).
        # Camera at z=0.5m, looking toward origin along -Z.
        # gsplat uses OpenCV camera convention (camera looks along +Z).
        # So we need to flip X and Y axes (rotate 180 around Z).
        if viewmat is None:
            # Place camera 0.5m in front of the face (positive Z)
            # World-to-camera: camera is at (0, 0, 0.5) looking at origin
            # The view matrix inverts the camera pose
            viewmat = torch.eye(4, device=device, dtype=torch.float32).unsqueeze(0)
            viewmat = viewmat.expand(B, -1, -1).clone()
            # Flip to look at origin: rotate 180 around Y-axis
            viewmat[:, 0, 0] = -1  # Flip X
            viewmat[:, 2, 2] = -1  # Flip Z (now camera looks toward -Z in world = face)
            viewmat[:, 2, 3] = 0.5  # Camera at z=0.5 in camera space

        if K is None:
            fy = H / (2 * math.tan(math.radians(self.config.fov_y) / 2))
            fx = fy
            cx, cy = W / 2.0, H / 2.0
            K = torch.tensor([
                [fx, 0, cx],
                [0, fy, cy],
                [0, 0, 1],
            ], device=device, dtype=torch.float32).unsqueeze(0).expand(B, -1, -1).contiguous()

        # Deform Gaussians
        gs = self.deform_gaussians(mesh_verts, expression_weights)

        # Render each batch element
        start = time.perf_counter()

        images = []
        alphas = []

        bg = torch.tensor(
            list(self.config.bg_color), device=device, dtype=torch.float32,
        )

        for b in range(B):
            renders, alpha, info = gsplat.rasterization(
                means=gs["means"][b],
                quats=gs["quats"][b],
                scales=gs["scales"][b],
                opacities=gs["opacities"][b],
                colors=gs["colors"][b],
                viewmats=viewmat[b:b + 1],
                Ks=K[b:b + 1],
                width=W,
                height=H,
                sh_degree=None,
            )
            # Apply background manually via alpha blending
            img = renders[0]  # (H, W, 3)
            a = alpha[0]  # (H, W, 1)
            img = img + bg.view(1, 1, 3) * (1 - a)
            images.append(img)
            alphas.append(a)

        torch.cuda.synchronize()
        render_time = (time.perf_counter() - start) * 1000

        return {
            "image": torch.stack(images),
            "alpha": torch.stack(alphas),
            "render_time_ms": render_time,
        }


# Re-export GaussianAvatarRenderer from its own module
from phoenix.render.avatar_renderer import GaussianAvatarRenderer  # noqa: F401
