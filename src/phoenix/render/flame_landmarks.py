"""FLAME 68-landmark tables and projection helpers for the FLAME fitter.

Split out of ``phoenix.render.flame_fitter`` (pure move): the FLAME mesh
vertex indices of the 68 Multi-PIE landmarks, the insightface-106 -> 68
mapping, landmark vertex gathering and weak-perspective projection.
"""

from __future__ import annotations

import torch

# --------------------------------------------------------------------------- #
# FLAME 68-landmark vertex indices (standard from FLAME codebase)
# These map the 68 Multi-PIE landmarks to FLAME mesh vertex indices
# --------------------------------------------------------------------------- #
FLAME_LMK_68 = [
    # Jaw contour (0-16)
    3572, 2643, 2585, 2546, 2510, 3636, 3503, 3410, 3336,
    3270, 3206, 3144, 3075, 2989, 2905, 2832, 2774,
    # Right eyebrow (17-21)
    3862, 3854, 3848, 3839, 3820,
    # Left eyebrow (22-26)
    2437, 2383, 2345, 2315, 2286,
    # Nose bridge (27-30)
    1610, 1647, 1691, 1731,
    # Nose bottom (31-35)
    2162, 2173, 2188, 1830, 1803,
    # Right eye (36-41)
    3712, 3716, 3721, 3726, 3727, 3718,
    # Left eye (42-47)
    2210, 2214, 2219, 2224, 2225, 2216,
    # Outer lip (48-59)
    3543, 3509, 3466, 3423, 3390, 3380, 3354, 3362,
    3378, 3395, 3437, 3490,
    # Inner lip (60-67)
    3502, 3456, 3410, 3372, 3361, 3373, 3411, 3457,
]

# --------------------------------------------------------------------------- #
# Mapping from insightface 106 landmarks to FLAME 68 landmarks
# InsightFace 106 layout (approx):
#   0-32:  face contour (33 points)
#   33-37: right eyebrow (5 points)
#   38-42: left eyebrow (5 points)
#   43-46: nose bridge (4 points)
#   47-51: nose bottom (5 points)
#   52-57: right eye (6 points)
#   58-63: left eye (6 points)
#   64-71: outer lip upper (8 points)
#   72-75: outer lip lower (4 points)
#   76-83: inner lip upper (8 points)
#   84-87: inner lip lower (4 points)
#   88-95: more points
#   96-103: pupil/extra
#   104-105: extra
# --------------------------------------------------------------------------- #

# We select a subset of insightface-106 that aligns well with the 68 scheme.
# The mapping is: INSIGHT106_TO_68[i] = index in the 106 array
# corresponding to the i-th 68-landmark.
INSIGHT106_TO_68 = [
    # Jaw contour (0-16): 106-format uses 0-32 for contour (33 pts)
    # We pick every 2nd point from the 33-pt contour
    0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32,
    # Right eyebrow (17-21): indices 33-37
    33, 34, 35, 36, 37,
    # Left eyebrow (22-26): indices 38-42
    42, 41, 40, 39, 38,
    # Nose bridge (27-30): indices 43-46
    43, 44, 45, 46,
    # Nose bottom (31-35): indices 47-51
    47, 48, 49, 50, 51,
    # Right eye (36-41): indices 52-57
    52, 53, 54, 55, 56, 57,
    # Left eye (42-47): indices 58-63
    58, 59, 60, 61, 62, 63,
    # Outer lip (48-59):
    # upper: 64,65,66,67,68,69,70,71 (8 pts)
    # lower: 72,73,74,75 (4 pts)
    # We need 12 pts for outer lip in 68 scheme
    64, 65, 66, 67, 68, 69, 70, 71, 75, 74, 73, 72,
    # Inner lip (60-67):
    # upper: 76,77,78,79 (pick 4 from 8)
    # lower: 84,85,86,87 (pick 4 from 4)
    76, 78, 80, 82, 87, 85, 83, 81,
]


def _get_flame_lmk_verts(
    flame_model: torch.nn.Module,
    shape_params: torch.Tensor,
    expression_params: torch.Tensor,
    jaw_pose: torch.Tensor,
) -> torch.Tensor:
    """Get FLAME 68-landmark 3D positions.

    Args:
        flame_model: FLAME model instance.
        shape_params: (B, 300) shape coefficients.
        expression_params: (B, 100) expression coefficients.
        jaw_pose: (B, 3) jaw rotation axis-angle.

    Returns:
        (B, 68, 3) landmark 3D positions.
    """
    verts = flame_model(shape_params, expression_params, jaw_pose=jaw_pose)
    lmk_idx = torch.tensor(FLAME_LMK_68, device=verts.device, dtype=torch.long)
    return verts[:, lmk_idx]


def _project_weak_perspective(
    pts3d: torch.Tensor,
    scale: torch.Tensor,
    tx: torch.Tensor,
    ty: torch.Tensor,
) -> torch.Tensor:
    """Weak-perspective projection: 2D = scale * (x, y) + (tx, ty).

    Args:
        pts3d: (B, N, 3) 3D points.
        scale: (B, 1) scale factor.
        tx: (B, 1) x-translation.
        ty: (B, 1) y-translation.

    Returns:
        (B, N, 2) projected 2D points.
    """
    xy = pts3d[:, :, :2]  # (B, N, 2)
    proj = scale.unsqueeze(1) * xy  # (B, N, 2)
    proj[:, :, 0] = proj[:, :, 0] + tx
    proj[:, :, 1] = proj[:, :, 1] + ty
    return proj
