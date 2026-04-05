"""High-level Gaussian Avatar Renderer for the Phoenix avatar engine.

Ties together FLAME parametric head model, Gaussian Splatting model,
and camera setup into a simple render_frame() interface.

Usage:
    renderer = GaussianAvatarRenderer(config)
    renderer.initialize()
    result = renderer.render_frame(expression_coeffs, jaw_pose)
    image = result['image']  # (H, W, 3) float32

Performance on RTX 5090 (tex_size=256, 1280x720):
    ~55 FPS, 59K Gaussians, ~150MB VRAM.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as Fn

from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarModel

# Allow safe loading of our config dataclass in torch.load
try:
    torch.serialization.add_safe_globals([AvatarRenderConfig])
except AttributeError:
    pass  # Older PyTorch versions don't have this

logger = logging.getLogger(__name__)


class GaussianAvatarRenderer:
    """High-level avatar renderer that ties together FLAME and gsplat.

    This is the main interface for the Phoenix avatar engine.
    It manages the FLAME model, Gaussian avatar, and camera setup.

    Usage:
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()
        result = renderer.render_frame(expression_coeffs, jaw_pose)
        image = result['image']  # (H, W, 3) uint8

    Args:
        config: Rendering configuration.
    """

    def __init__(self, config: AvatarRenderConfig | None = None) -> None:
        self.config = config or AvatarRenderConfig()
        self.device = torch.device(f"cuda:{self.config.device_id}")
        self._flame = None
        self._avatar: GaussianAvatarModel | None = None
        self._ready = False

        # Cache for neutral mesh
        self._neutral_verts: torch.Tensor | None = None
        self._shape_params: torch.Tensor | None = None

        # Performance tracking
        self._frame_count = 0
        self._total_render_ms = 0.0

        # CUDA 13.2: Stream priorities for pipeline parallelism.
        # High-priority stream (-1) for the render path (gsplat + compositor)
        # so it preempts lower-priority work on the same GPU.
        # Normal-priority stream (0) for non-critical background work
        # (e.g. stats collection, prefetch, deferred uploads).
        self._render_stream = torch.cuda.Stream(
            device=self.device, priority=-1,
        )
        self._aux_stream = torch.cuda.Stream(
            device=self.device, priority=0,
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def avg_render_ms(self) -> float:
        if self._frame_count == 0:
            return 0.0
        return self._total_render_ms / self._frame_count

    @property
    def avg_fps(self) -> float:
        ms = self.avg_render_ms
        return 1000.0 / ms if ms > 0 else 0.0

    def initialize(
        self,
        shape_params: torch.Tensor | None = None,
    ) -> None:
        """Initialize the FLAME model and bind Gaussians.

        Args:
            shape_params: (300,) identity shape parameters for the avatar.
                If None, uses neutral (zero) shape.
        """
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        logger.info("Initializing Gaussian Avatar Renderer...")

        # Create FLAME model
        flame_config = FlameModelConfig()
        self._flame = FlameModel(flame_config)
        self._flame = self._flame.to(self.device)

        # Set identity shape
        if shape_params is not None:
            self._shape_params = shape_params.to(self.device).unsqueeze(0)
        else:
            self._shape_params = torch.zeros(
                1, flame_config.num_shape_params,
                device=self.device, dtype=torch.float32,
            )

        # Create Gaussian avatar model
        self._avatar = GaussianAvatarModel(self._flame, self.config)
        self._avatar = self._avatar.to(self.device)

        # Bind Gaussians to FLAME mesh
        num_gs = self._avatar.bind_to_mesh()
        logger.info("Avatar bound: %d Gaussians", num_gs)

        # Cache neutral mesh
        neutral_exp = torch.zeros(
            1, flame_config.num_exp_params,
            device=self.device, dtype=torch.float32,
        )
        self._neutral_verts = self._flame(self._shape_params, neutral_exp)

        self._ready = True
        logger.info(
            "Gaussian Avatar Renderer ready: %d Gaussians, %dx%d, VRAM %.1fMB",
            num_gs, self.config.width, self.config.height,
            torch.cuda.memory_allocated(self.device) / 1e6,
        )

    def render_frame(
        self,
        expression_params: torch.Tensor | None = None,
        jaw_pose: torch.Tensor | None = None,
        neck_pose: torch.Tensor | None = None,
        eye_pose: torch.Tensor | None = None,
        viewmat: torch.Tensor | None = None,
    ) -> dict[str, Any]:
        """Render a single avatar frame.

        Args:
            expression_params: (num_exp,) expression coefficients [0-1].
            jaw_pose: (3,) jaw rotation axis-angle.
            neck_pose: (3,) neck rotation axis-angle.
            eye_pose: (6,) left+right eye rotation axis-angle.
            viewmat: (4, 4) camera view matrix.

        Returns:
            Dict with:
                'image': (H, W, 3) float32 in [0, 1]
                'alpha': (H, W, 1) float32 in [0, 1]
                'render_time_ms': float
                'fps': float
        """
        if not self._ready:
            raise RuntimeError("Renderer not initialized. Call initialize() first.")

        device = self.device

        # CUDA 13.2: Run the entire render path on the high-priority
        # stream so it preempts lower-priority GPU work.
        with torch.cuda.stream(self._render_stream):
            return self._render_frame_impl(
                expression_params, jaw_pose, neck_pose, eye_pose, viewmat,
            )

    def _render_frame_impl(
        self,
        expression_params: torch.Tensor | None = None,
        jaw_pose: torch.Tensor | None = None,
        neck_pose: torch.Tensor | None = None,
        eye_pose: torch.Tensor | None = None,
        viewmat: torch.Tensor | None = None,
    ) -> dict[str, Any]:
        """Internal render implementation, runs on self._render_stream."""
        device = self.device

        # Prepare expression params
        if expression_params is not None:
            exp = expression_params.to(device).unsqueeze(0)
            # Pad or truncate to num_exp
            target_dim = self._flame.num_exp
            if exp.shape[1] < target_dim:
                exp = Fn.pad(exp, (0, target_dim - exp.shape[1]))
            elif exp.shape[1] > target_dim:
                exp = exp[:, :target_dim]
        else:
            exp = torch.zeros(
                1, self._flame.num_exp,
                device=device, dtype=torch.float32,
            )

        # Prepare jaw/neck/eye poses
        jaw = jaw_pose.to(device).unsqueeze(0) if jaw_pose is not None else None
        neck = neck_pose.to(device).unsqueeze(0) if neck_pose is not None else None
        eye = eye_pose.to(device).unsqueeze(0) if eye_pose is not None else None

        # Deform FLAME mesh
        verts = self._flame(
            self._shape_params, exp,
            jaw_pose=jaw, neck_pose=neck, eye_pose=eye,
        )

        # Prepare viewmat
        if viewmat is not None:
            vm = viewmat.to(device).unsqueeze(0) if viewmat.dim() == 2 else viewmat.to(device)
        else:
            vm = None

        # Render
        result = self._avatar.render(verts, expression_weights=exp, viewmat=vm)

        self._frame_count += 1
        self._total_render_ms += result["render_time_ms"]

        return {
            "image": result["image"][0],  # (H, W, 3)
            "alpha": result["alpha"][0],  # (H, W, 1)
            "render_time_ms": result["render_time_ms"],
            "fps": 1000.0 / max(result["render_time_ms"], 0.01),
            "num_gaussians": self._avatar.num_gaussians,
        }

    def save_model(self, path: str | Path) -> None:
        """Save the trained avatar model.

        Args:
            path: Output path for the model checkpoint.
        """
        if not self._ready:
            raise RuntimeError("No model to save.")

        torch.save({
            "avatar_state_dict": self._avatar.state_dict(),
            "shape_params": self._shape_params,
            "config": self.config,
        }, str(path))
        logger.info("Avatar model saved to %s", path)

    def load_model(self, path: str | Path) -> None:
        """Load a trained avatar model.

        Args:
            path: Path to the model checkpoint.
        """
        checkpoint = torch.load(str(path), map_location=self.device)
        self._shape_params = checkpoint["shape_params"].to(self.device)

        # Re-initialize with loaded config
        loaded_config = checkpoint.get("config", self.config)
        self.config = loaded_config
        self.initialize(shape_params=self._shape_params.squeeze(0))

        # Load avatar weights
        self._avatar.load_state_dict(checkpoint["avatar_state_dict"])
        logger.info("Avatar model loaded from %s", path)

    @classmethod
    def load_trained(
        cls,
        model_path: str | Path | None = None,
        flame_params_path: str | Path | None = None,
        device_id: int = 0,
    ) -> "GaussianAvatarRenderer":
        """Load a trained Gaussian avatar and return a ready renderer.

        This is the convenience entry point for real-time use. It:
        1. Loads the trained Gaussian model checkpoint
        2. Loads FLAME params for reference poses
        3. Returns a renderer that can immediately render frames

        Args:
            model_path: Path to the trained Gaussian model (.pt).
                Default: ~/.clipcannon/models/santa/gaussian_avatar.pt
            flame_params_path: Path to fitted FLAME params (.npz).
                Default: ~/.clipcannon/models/santa/flame_params.npz
            device_id: CUDA device index.

        Returns:
            An initialized GaussianAvatarRenderer ready for real-time use.
        """
        default_dir = Path.home() / ".clipcannon" / "models" / "santa"
        if model_path is None:
            model_path = default_dir / "gaussian_avatar.pt"
        if flame_params_path is None:
            flame_params_path = default_dir / "flame_params.npz"

        model_path = Path(model_path)
        flame_params_path = Path(flame_params_path)

        if not model_path.exists():
            raise FileNotFoundError(f"Trained model not found: {model_path}")
        if not flame_params_path.exists():
            raise FileNotFoundError(f"FLAME params not found: {flame_params_path}")

        logger.info("Loading trained avatar from %s", model_path)

        # Load checkpoint to get config
        checkpoint = torch.load(str(model_path), map_location=f"cuda:{device_id}")
        config = checkpoint.get("config", AvatarRenderConfig(device_id=device_id))

        # Create renderer with the saved config
        renderer = cls(config)
        renderer.initialize()

        # Load trained weights
        renderer._avatar.load_state_dict(checkpoint["avatar_state_dict"])
        logger.info(
            "Trained avatar loaded: %d Gaussians, step %d",
            checkpoint.get("num_gaussians", renderer._avatar.num_gaussians),
            checkpoint.get("step", -1),
        )

        # Store reference FLAME params for downstream use
        import numpy as np
        flame_data = np.load(str(flame_params_path))
        renderer._ref_expressions = torch.from_numpy(
            flame_data["expression"],
        ).to(renderer.device)
        renderer._ref_jaw_poses = torch.from_numpy(
            flame_data["jaw_pose"],
        ).to(renderer.device)
        renderer._ref_timestamps = flame_data["timestamps"]
        logger.info(
            "Loaded %d reference FLAME frames",
            len(renderer._ref_timestamps),
        )

        return renderer
