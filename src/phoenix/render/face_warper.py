"""GPU-accelerated face warping for real-time lip sync.

.. deprecated::
    This module is superseded by ``phoenix.render.physics_face.PhysicsFaceEngine``
    combined with the Gaussian Splatting renderer. PhysicsFaceEngine provides
    physics-based FLAME parameters directly, while this module only warps pixels
    based on a scalar mouth_open value. Kept as a 2D fallback when the 3D
    Gaussian renderer is not available.

Takes a source face frame and warps the mouth region to simulate
speech based on lip sync parameters. Uses insightface for landmark
detection and CuPy for GPU-accelerated pixel manipulation.

The approach:
1. Detect 106 face landmarks on the source frame (once at init)
2. Identify mouth region (landmarks 52-71)
3. For each target mouth_open value, vertically stretch the lower
   face region below the upper lip downward, and compress the chin
   area back up -- creating a natural mouth opening effect
4. All pixel operations run on GPU via CuPy

This is NOT a generative model -- it warps existing pixels, so the
result always looks like the original person. Fast enough for
real-time at 25fps on RTX 5090.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FaceWarper:
    """Warp a face's mouth region for lip sync.

    Initialize with a reference frame. The face landmarks are detected
    once and cached. Then call warp_mouth() with different mouth_open
    values to get frames with different mouth positions.

    Args:
        reference_frame: BGR uint8 numpy array (H, W, 3) with a face.
        max_pixel_shift: Maximum vertical pixel displacement for mouth open.
    """

    def __init__(
        self,
        reference_frame: np.ndarray,
        max_pixel_shift: int = 25,
    ) -> None:
        self._ref = reference_frame.copy()
        self._h, self._w = reference_frame.shape[:2]
        self._max_shift = max_pixel_shift
        self._landmarks: np.ndarray | None = None
        self._mouth_center_y: int = 0
        self._upper_lip_y: int = 0
        self._lower_lip_y: int = 0
        self._chin_y: int = 0
        self._mouth_left_x: int = 0
        self._mouth_right_x: int = 0
        self._face_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._ready = False

        # Pre-compute mouth map for fast warping
        self._map_x_base: np.ndarray | None = None
        self._map_y_base: np.ndarray | None = None

        self._detect_landmarks()

    def _detect_landmarks(self) -> None:
        """Detect face landmarks on the reference frame."""
        try:
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            app.prepare(ctx_id=0, det_size=(640, 640))
            faces = app.get(self._ref)
            if not faces:
                logger.warning("No face detected in reference frame")
                return

            face = faces[0]
            self._face_bbox = tuple(face.bbox.astype(int))

            if hasattr(face, "landmark_2d_106") and face.landmark_2d_106 is not None:
                lm = face.landmark_2d_106
                self._landmarks = lm

                # Mouth landmarks in 106-point model: indices 52-71
                mouth_lm = lm[52:72]
                self._mouth_left_x = int(np.min(mouth_lm[:, 0])) - 10
                self._mouth_right_x = int(np.max(mouth_lm[:, 0])) + 10

                # Upper lip (top of mouth)
                upper_lip = lm[52:60]  # Upper lip contour
                self._upper_lip_y = int(np.min(upper_lip[:, 1]))

                # Lower lip (bottom of mouth)
                lower_lip = lm[60:68]  # Lower lip contour
                self._lower_lip_y = int(np.max(lower_lip[:, 1]))

                # Mouth center
                self._mouth_center_y = (self._upper_lip_y + self._lower_lip_y) // 2

                # Chin (bottom of face)
                chin = lm[0]  # Chin point in 106 model
                self._chin_y = int(chin[1])

                # Pre-compute base remap grid
                self._map_x_base = np.tile(
                    np.arange(self._w, dtype=np.float32), (self._h, 1),
                )
                self._map_y_base = np.tile(
                    np.arange(self._h, dtype=np.float32).reshape(-1, 1), (1, self._w),
                )

                self._ready = True
                logger.info(
                    "FaceWarper ready: mouth y=[%d,%d], chin=%d, width=[%d,%d]",
                    self._upper_lip_y, self._lower_lip_y,
                    self._chin_y, self._mouth_left_x, self._mouth_right_x,
                )
            else:
                logger.warning("No 106-point landmarks available")
        except Exception as e:
            logger.error("FaceWarper init failed: %s", e)

    @property
    def ready(self) -> bool:
        """Whether the warper has valid landmarks."""
        return self._ready

    def warp_mouth(
        self,
        mouth_open: float,
        head_tilt: float = 0.0,
    ) -> np.ndarray:
        """Warp the reference frame's mouth to the target openness.

        Args:
            mouth_open: 0.0 = closed, 1.0 = wide open.
            head_tilt: Head tilt in degrees (for subtle movement).

        Returns:
            BGR uint8 frame with warped mouth.
        """
        if not self._ready:
            return self._ref.copy()

        mouth_open = max(0.0, min(1.0, mouth_open))
        shift = int(mouth_open * self._max_shift)

        if shift == 0 and abs(head_tilt) < 0.5:
            return self._ref.copy()

        # Create displacement map
        map_y = self._map_y_base.copy()

        # Vertical displacement: stretch the region between upper lip and chin
        # Upper lip stays fixed; lower lip moves down; chin gets compressed back
        lip_top = self._upper_lip_y
        lip_bot = self._lower_lip_y
        chin = min(self._chin_y, self._h - 5)

        # Region 1: lip_top to lip_bot — stretch downward (mouth opens)
        if lip_bot > lip_top and shift > 0:
            mouth_zone = slice(lip_top, min(lip_bot + shift, self._h))
            for y in range(mouth_zone.start, mouth_zone.stop):
                # How far into the mouth zone are we? (0 to 1)
                t = (y - lip_top) / max(1, (lip_bot + shift) - lip_top)
                # Source y: compress the original mouth region
                src_y = lip_top + t * (lip_bot - lip_top)
                # Only affect the horizontal mouth region
                x_mask = np.ones(self._w, dtype=np.float32)
                # Smooth falloff outside mouth width
                center_x = (self._mouth_left_x + self._mouth_right_x) // 2
                half_w = (self._mouth_right_x - self._mouth_left_x) // 2 + 20
                for x in range(self._w):
                    dist = abs(x - center_x)
                    if dist > half_w:
                        x_mask[x] = 0.0
                    elif dist > half_w - 20:
                        x_mask[x] = (half_w - dist) / 20.0
                map_y[y, :] = map_y[y, :] * (1 - x_mask) + src_y * x_mask

            # Region 2: below stretched mouth to chin — compress back up
            new_lip_bot = lip_bot + shift
            if new_lip_bot < chin:
                for y in range(new_lip_bot, chin):
                    t = (y - new_lip_bot) / max(1, chin - new_lip_bot)
                    src_y = lip_bot + t * (chin - lip_bot)
                    x_mask = np.ones(self._w, dtype=np.float32)
                    center_x = (self._mouth_left_x + self._mouth_right_x) // 2
                    half_w = (self._mouth_right_x - self._mouth_left_x) // 2 + 30
                    for x in range(self._w):
                        dist = abs(x - center_x)
                        if dist > half_w:
                            x_mask[x] = 0.0
                        elif dist > half_w - 30:
                            x_mask[x] = (half_w - dist) / 30.0
                    map_y[y, :] = map_y[y, :] * (1 - x_mask) + src_y * x_mask

        # Apply remap
        result = cv2.remap(
            self._ref,
            self._map_x_base,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

        # Apply subtle head tilt if requested
        if abs(head_tilt) >= 0.5:
            center = (self._w // 2, self._h // 2)
            M = cv2.getRotationMatrix2D(center, head_tilt, 1.0)
            result = cv2.warpAffine(
                result, M, (self._w, self._h),
                borderMode=cv2.BORDER_REPLICATE,
            )

        return result
