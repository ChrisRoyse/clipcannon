"""FLAME parametric head model for Gaussian Splatting avatar.

Loads the FLAME 3D Morphable Model and provides forward kinematics
to deform a template mesh given shape, expression, jaw pose, and
neck pose parameters. Uses clean numpy data (no chumpy dependency).

FLAME outputs:
  5023 vertices, 9976 faces, 400 shape + expression blendshapes.
  The first 300 shape dirs are identity, next 100 are expression.

References:
  Li et al., "Learning a model of facial shape and expression
  from 4D scans", SIGGRAPH Asia 2017.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# Default paths relative to project root
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "models" / "FLAME2020"


@dataclass(frozen=True)
class FlameModelConfig:
    """Configuration for the FLAME model.

    Attributes:
        data_dir: Directory containing FLAME model files.
        num_shape_params: Number of identity shape parameters to use.
        num_exp_params: Number of expression parameters to use.
        dtype: Tensor dtype for computation.
        add_teeth: Whether to add procedural teeth geometry.
    """

    data_dir: Path = _DEFAULT_DATA_DIR
    num_shape_params: int = 300
    num_exp_params: int = 100
    dtype: torch.dtype = torch.float32
    add_teeth: bool = True


def _batch_rodrigues(rot_vecs: torch.Tensor) -> torch.Tensor:
    """Convert axis-angle rotations to rotation matrices.

    Args:
        rot_vecs: (B, 3) axis-angle rotation vectors.

    Returns:
        (B, 3, 3) rotation matrices.
    """
    batch_size = rot_vecs.shape[0]
    angle = torch.norm(rot_vecs + 1e-8, dim=1, keepdim=True)
    rot_dir = rot_vecs / angle

    cos = torch.cos(angle).unsqueeze(-1)
    sin = torch.sin(angle).unsqueeze(-1)

    # Bx1 arrays
    rx, ry, rz = rot_dir[:, 0:1], rot_dir[:, 1:2], rot_dir[:, 2:3]

    zeros = torch.zeros(batch_size, 1, device=rot_vecs.device, dtype=rot_vecs.dtype)
    K = torch.cat([zeros, -rz, ry, rz, zeros, -rx, -ry, rx, zeros], dim=1)
    K = K.reshape(batch_size, 3, 3)

    eye = torch.eye(3, device=rot_vecs.device, dtype=rot_vecs.dtype).unsqueeze(0)
    R = eye + sin * K + (1 - cos) * torch.bmm(K, K)
    return R


def _vertices2joints(J_regressor: torch.Tensor, vertices: torch.Tensor) -> torch.Tensor:
    """Regress joint locations from mesh vertices."""
    return torch.einsum("bik,ji->bjk", [vertices, J_regressor])


def _blend_shapes(betas: torch.Tensor, shapedirs: torch.Tensor) -> torch.Tensor:
    """Apply blendshape displacements."""
    return torch.einsum("bl,mkl->bmk", [betas, shapedirs])


def _make_4x4(R: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
    """Build a (B, 4, 4) rigid transform from rotation and translation.

    Args:
        R: (B, 3, 3) rotation matrix.
        t: (B, 3) translation vector.

    Returns:
        (B, 4, 4) homogeneous transform.
    """
    B = R.shape[0]
    T = torch.zeros(B, 4, 4, device=R.device, dtype=R.dtype)
    T[:, :3, :3] = R
    T[:, :3, 3] = t
    T[:, 3, 3] = 1.0
    return T


def _lbs(
    betas: torch.Tensor,
    full_pose: torch.Tensor,
    v_template: torch.Tensor,
    shapedirs: torch.Tensor,
    posedirs: torch.Tensor,
    J_regressor: torch.Tensor,
    parents: torch.Tensor,
    lbs_weights: torch.Tensor,
) -> torch.Tensor:
    """Linear Blend Skinning for FLAME.

    Follows the standard SMPL/FLAME LBS implementation:
    1. Apply shape + expression blendshapes to get v_shaped
    2. Regress joint locations from v_shaped
    3. Apply pose corrective blendshapes
    4. Build per-joint world transforms via forward kinematics
    5. Remove rest-pose joint locations (subtract rest transform)
    6. Blend per-vertex transforms using skinning weights
    7. Apply blended transforms to posed vertices

    Args:
        betas: (B, num_betas) shape + expression parameters.
        full_pose: (B, J, 3, 3) rotation matrices for each joint.
        v_template: (V, 3) template vertices.
        shapedirs: (V, 3, num_betas) blendshape directions.
        posedirs: (V, 3, (J-1)*9) pose corrective directions.
        J_regressor: (J, V) joint regressor.
        parents: (J,) kinematic tree parent indices.
        lbs_weights: (V, J) blend weights.

    Returns:
        (B, V, 3) posed vertices.
    """
    batch_size = betas.shape[0]
    device = betas.device
    dtype = v_template.dtype
    num_joints = full_pose.shape[1]

    # 1. Shape blend: add identity + expression offsets
    v_shaped = v_template.unsqueeze(0) + _blend_shapes(betas, shapedirs)

    # 2. Regress joint locations from shaped vertices
    J = _vertices2joints(J_regressor, v_shaped)  # (B, J, 3)

    # 3. Pose corrective blendshapes
    ident = torch.eye(3, device=device, dtype=dtype)
    rot_mats = full_pose[:, 1:]  # Skip root joint (B, J-1, 3, 3)
    pose_feature = (rot_mats - ident).reshape(batch_size, -1)  # (B, (J-1)*9)
    # posedirs is (V, 3, (J-1)*9), reshape to ((J-1)*9, V*3)
    posedirs_flat = posedirs.reshape(-1, posedirs.shape[-1]).T  # ((J-1)*9, V*3)
    pose_offsets = torch.matmul(pose_feature, posedirs_flat)  # (B, V*3)
    pose_offsets = pose_offsets.reshape(batch_size, -1, 3)  # (B, V, 3)
    v_posed = v_shaped + pose_offsets

    # 4. Forward kinematics: build world transforms for each joint
    # Each joint's local transform is relative to its parent
    world_transforms = [None] * num_joints

    for j_idx in range(num_joints):
        local_rot = full_pose[:, j_idx]  # (B, 3, 3)
        local_trans = J[:, j_idx]  # (B, 3)

        if parents[j_idx] < 0:
            # Root joint: world = local
            world_transforms[j_idx] = _make_4x4(local_rot, local_trans)
        else:
            parent_idx = parents[j_idx].item()
            # Local translation is relative to parent joint
            rel_trans = local_trans - J[:, parent_idx]
            local_T = _make_4x4(local_rot, rel_trans)
            world_transforms[j_idx] = torch.bmm(
                world_transforms[parent_idx], local_T,
            )

    # Stack all world transforms: (B, J, 4, 4)
    G = torch.stack(world_transforms, dim=1)

    # 5. Remove rest-pose joint locations
    # The rest-pose transform for joint j is: translate to J[j]
    # We need G_final = G_world * inv(G_rest)
    # Since G_rest is just translation, inv(G_rest) subtracts J from the translation
    rest_J_homo = torch.zeros(batch_size, num_joints, 4, 1, device=device, dtype=dtype)
    rest_J_homo[:, :, :3, 0] = J
    rest_J_homo[:, :, 3, 0] = 1.0

    # The correction: subtract G * rest_joint_position from G's translation
    correction = torch.matmul(G, rest_J_homo)  # (B, J, 4, 1)
    G_corrected = G.clone()
    G_corrected[:, :, :, 3:] -= correction

    # 6. Blend per-vertex transforms using skinning weights
    # W: (B, V, J), G_flat: (B, J, 16)
    W = lbs_weights.unsqueeze(0).expand(batch_size, -1, -1)
    G_flat = G_corrected.reshape(batch_size, num_joints, 16)
    T = torch.bmm(W, G_flat).reshape(batch_size, -1, 4, 4)  # (B, V, 4, 4)

    # 7. Apply blended transforms to posed vertices
    v_homo = torch.cat([
        v_posed,
        torch.ones(batch_size, v_posed.shape[1], 1, device=device, dtype=dtype),
    ], dim=-1)  # (B, V, 4)

    v_out = torch.einsum("bvij,bvj->bvi", T, v_homo)[:, :, :3]

    return v_out


class FlameModel(nn.Module):
    """FLAME 3D Morphable Model for head avatar.

    Provides differentiable mesh deformation from parametric inputs.
    Uses pre-cleaned numpy data to avoid chumpy dependency.

    Args:
        config: FlameModelConfig with paths and parameter counts.
    """

    def __init__(self, config: FlameModelConfig | None = None) -> None:
        super().__init__()
        self.config = config or FlameModelConfig()

        # Load clean numpy data
        clean_path = self.config.data_dir / "flame_clean.npz"
        if not clean_path.exists():
            raise FileNotFoundError(
                f"FLAME clean data not found at {clean_path}. "
                "Run the FLAME model conversion script first."
            )

        data = np.load(str(clean_path))
        dtype = self.config.dtype

        # Template mesh
        v_template = torch.from_numpy(data["v_template"]).to(dtype)
        self.register_buffer("v_template", v_template)

        faces = torch.from_numpy(data["f"].astype(np.int64))
        self.register_buffer("faces", faces)

        # Blendshapes: first num_shape identity, then num_exp expression
        shapedirs_full = torch.from_numpy(data["shapedirs"]).to(dtype)
        n_shape = min(self.config.num_shape_params, 300)
        n_exp = min(self.config.num_exp_params, 100)
        shapedirs = torch.cat([
            shapedirs_full[:, :, :n_shape],
            shapedirs_full[:, :, 300:300 + n_exp],
        ], dim=2)
        self.register_buffer("shapedirs", shapedirs)

        # Pose corrective blendshapes
        posedirs = torch.from_numpy(data["posedirs"]).to(dtype)
        self.register_buffer("posedirs", posedirs)

        # Joint regressor
        J_regressor = torch.from_numpy(data["J_regressor"]).to(dtype)
        self.register_buffer("J_regressor", J_regressor)

        # Kinematic tree
        kintree = data["kintree_table"]
        parents = torch.from_numpy(kintree[0].astype(np.int64))
        parents[0] = -1
        self.register_buffer("parents", parents)

        # Blend skinning weights
        lbs_weights = torch.from_numpy(data["weights"]).to(dtype)
        self.register_buffer("lbs_weights", lbs_weights)

        # Eyelid blendshapes
        l_eyelid_path = self.config.data_dir / "l_eyelid.npy"
        r_eyelid_path = self.config.data_dir / "r_eyelid.npy"
        if l_eyelid_path.exists():
            self.register_buffer(
                "l_eyelid",
                torch.from_numpy(np.load(str(l_eyelid_path))).to(dtype).unsqueeze(0),
            )
            self.register_buffer(
                "r_eyelid",
                torch.from_numpy(np.load(str(r_eyelid_path))).to(dtype).unsqueeze(0),
            )
        else:
            self.register_buffer("l_eyelid", torch.zeros(1, v_template.shape[0], 3, dtype=dtype))
            self.register_buffer("r_eyelid", torch.zeros(1, v_template.shape[0], 3, dtype=dtype))

        # UV data for texture mapping and Gaussian binding
        uv_path = self.config.data_dir / "flame_uv.npz"
        if uv_path.exists():
            uv_data = np.load(str(uv_path))
            self.register_buffer("uvs", torch.from_numpy(uv_data["vt"]).to(dtype))
            self.register_buffer(
                "uv_faces",
                torch.from_numpy(uv_data["ft"].astype(np.int64)),
            )
        else:
            logger.warning("FLAME UV data not found at %s", uv_path)
            self.register_buffer("uvs", torch.zeros(0, 2, dtype=dtype))
            self.register_buffer("uv_faces", torch.zeros(0, 3, dtype=torch.int64))

        self.num_vertices = v_template.shape[0]
        self.num_faces = faces.shape[0]
        self.num_shape = n_shape
        self.num_exp = n_exp

        logger.info(
            "FLAME model loaded: %d verts, %d faces, %d shape + %d exp params",
            self.num_vertices, self.num_faces, n_shape, n_exp,
        )

    def forward(
        self,
        shape_params: torch.Tensor,
        expression_params: torch.Tensor,
        jaw_pose: torch.Tensor | None = None,
        neck_pose: torch.Tensor | None = None,
        eye_pose: torch.Tensor | None = None,
        eyelid_params: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Compute deformed FLAME mesh vertices.

        Args:
            shape_params: (B, num_shape) identity shape coefficients.
            expression_params: (B, num_exp) expression coefficients.
            jaw_pose: (B, 3) jaw rotation axis-angle. Default: zero.
            neck_pose: (B, 3) neck rotation axis-angle. Default: zero.
            eye_pose: (B, 6) left+right eye rotation axis-angle. Default: zero.
            eyelid_params: (B, 2) left/right eyelid weights. Default: None.

        Returns:
            (B, V, 3) deformed vertex positions.
        """
        batch_size = shape_params.shape[0]
        device = shape_params.device
        dtype = self.v_template.dtype

        # Default poses
        if jaw_pose is None:
            jaw_pose = torch.zeros(batch_size, 3, device=device, dtype=dtype)
        if neck_pose is None:
            neck_pose = torch.zeros(batch_size, 3, device=device, dtype=dtype)
        if eye_pose is None:
            eye_pose = torch.zeros(batch_size, 6, device=device, dtype=dtype)

        # Concatenate shape + expression params
        betas = torch.cat([shape_params, expression_params], dim=1)

        # Build rotation matrices for each joint
        # FLAME joints: root, neck, jaw, left_eye, right_eye
        root_rot = torch.eye(3, device=device, dtype=dtype).unsqueeze(0).expand(batch_size, -1, -1)
        neck_rot = _batch_rodrigues(neck_pose)
        jaw_rot = _batch_rodrigues(jaw_pose)
        leye_rot = _batch_rodrigues(eye_pose[:, :3])
        reye_rot = _batch_rodrigues(eye_pose[:, 3:])

        full_pose = torch.stack([root_rot, neck_rot, jaw_rot, leye_rot, reye_rot], dim=1)

        # Template with eyelid deformation
        v_template = self.v_template.clone()
        if eyelid_params is not None:
            v_template = v_template.unsqueeze(0).expand(batch_size, -1, -1).clone()
            v_template += self.l_eyelid * eyelid_params[:, 0:1, None]
            v_template += self.r_eyelid * eyelid_params[:, 1:2, None]
        else:
            v_template = v_template.unsqueeze(0).expand(batch_size, -1, -1)

        # Linear Blend Skinning
        vertices = _lbs(
            betas, full_pose, self.v_template,
            self.shapedirs, self.posedirs,
            self.J_regressor, self.parents,
            self.lbs_weights,
        )

        return vertices

    def get_neutral_vertices(self) -> torch.Tensor:
        """Get the neutral (zero-param) mesh vertices.

        Returns:
            (1, V, 3) neutral vertex positions.
        """
        device = self.v_template.device
        shape = torch.zeros(1, self.num_shape, device=device, dtype=self.v_template.dtype)
        expr = torch.zeros(1, self.num_exp, device=device, dtype=self.v_template.dtype)
        return self.forward(shape, expr)
