"""GPU model lifecycle manager for ClipCannon.

Manages loading and unloading ML models based on available VRAM,
reports GPU health, and determines whether models can run concurrently
or must be loaded sequentially.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from clipcannon.exceptions import GPUError
from clipcannon.gpu.precision import (
    auto_detect_precision,
    get_compute_capability,
)

logger = logging.getLogger(__name__)

# VRAM threshold in bytes: GPUs with >16 GB can run models concurrently
CONCURRENT_VRAM_THRESHOLD_BYTES = 16 * 1024 ** 3


@dataclass
class GPUHealthReport:
    """Snapshot of GPU health status.

    Attributes:
        device_name: GPU model name (e.g. "NVIDIA GeForce RTX 5090").
        compute_capability: CUDA compute capability string.
        vram_total_bytes: Total VRAM in bytes.
        vram_used_bytes: Currently allocated VRAM in bytes.
        vram_free_bytes: Available VRAM in bytes.
        precision: Selected precision format.
        concurrent_mode: Whether models can run concurrently.
        loaded_models: List of currently loaded model names.
        cpu_only: Whether running in CPU-only mode.
    """

    device_name: str
    compute_capability: str
    vram_total_bytes: int
    vram_used_bytes: int
    vram_free_bytes: int
    precision: str
    concurrent_mode: bool
    loaded_models: list[str]
    cpu_only: bool = False

    @property
    def vram_total_gb(self) -> float:
        """Total VRAM in gigabytes."""
        return self.vram_total_bytes / (1024 ** 3)

    @property
    def vram_used_gb(self) -> float:
        """Used VRAM in gigabytes."""
        return self.vram_used_bytes / (1024 ** 3)

    @property
    def vram_free_gb(self) -> float:
        """Free VRAM in gigabytes."""
        return self.vram_free_bytes / (1024 ** 3)

    @property
    def vram_usage_pct(self) -> float:
        """VRAM usage as a percentage (0.0-100.0)."""
        if self.vram_total_bytes == 0:
            return 0.0
        return (self.vram_used_bytes / self.vram_total_bytes) * 100.0

    def to_dict(self) -> dict[str, str | int | float | bool | list[str]]:
        """Serialize health report to a dictionary.

        Returns:
            Dictionary representation of the health report.
        """
        return {
            "device_name": self.device_name,
            "compute_capability": self.compute_capability,
            "vram_total_gb": round(self.vram_total_gb, 2),
            "vram_used_gb": round(self.vram_used_gb, 2),
            "vram_free_gb": round(self.vram_free_gb, 2),
            "vram_usage_pct": round(self.vram_usage_pct, 1),
            "precision": self.precision,
            "concurrent_mode": self.concurrent_mode,
            "loaded_models": self.loaded_models,
            "cpu_only": self.cpu_only,
        }


@dataclass
class _ModelEntry:
    """Internal record for a loaded model.

    Attributes:
        name: Model identifier.
        model: The loaded model object (torch.nn.Module or similar).
        vram_estimate_bytes: Estimated VRAM consumption.
        loaded_at: Timestamp when the model was loaded.
    """

    name: str
    model: object
    vram_estimate_bytes: int
    loaded_at: float = field(default_factory=time.time)


class ModelManager:
    """Manages ML model lifecycle based on available VRAM.

    On GPUs with >16 GB VRAM, models are kept loaded concurrently for
    zero-overhead pipeline execution. On smaller GPUs, models are loaded
    and unloaded sequentially, evicting LRU models when VRAM is tight.

    Attributes:
        device: CUDA device string (e.g. "cuda:0") or "cpu".
        precision: Auto-detected precision format.
        cpu_only: Whether running without GPU acceleration.
        concurrent: Whether models can be loaded concurrently.
    """

    def __init__(self, device: str = "cuda:0", max_vram_bytes: int | None = None) -> None:
        """Initialize the ModelManager.

        Auto-detects GPU capabilities and sets precision/concurrency mode.
        Falls back to CPU if no CUDA GPU is available.

        Args:
            device: CUDA device string or "cpu" for CPU-only mode.
            max_vram_bytes: Override for max VRAM (used in testing).
        """
        self._loaded_models: OrderedDict[str, _ModelEntry] = OrderedDict()
        self.cpu_only = False
        self.device = device
        self.precision = "fp32"
        self.concurrent = False
        self._vram_total: int = 0

        if device == "cpu":
            self.cpu_only = True
            self.precision = "fp32"
            logger.info("ModelManager initialized in CPU-only mode.")
            return

        try:
            import torch
        except ImportError:
            self.cpu_only = True
            self.device = "cpu"
            logger.warning("PyTorch not available. ModelManager running in CPU-only mode.")
            return

        if not torch.cuda.is_available():
            self.cpu_only = True
            self.device = "cpu"
            logger.warning("CUDA not available. ModelManager running in CPU-only mode.")
            return

        # Extract device index
        device_index = 0
        if ":" in device:
            try:
                device_index = int(device.split(":")[1])
            except (ValueError, IndexError):
                device_index = 0

        self.precision = auto_detect_precision(device_index)

        try:
            props = torch.cuda.get_device_properties(device_index)
            self._vram_total = max_vram_bytes if max_vram_bytes is not None else props.total_memory
            self.concurrent = self._vram_total > CONCURRENT_VRAM_THRESHOLD_BYTES
            logger.info(
                "ModelManager initialized: device=%s, VRAM=%.1f GB, precision=%s, concurrent=%s",
                device,
                self._vram_total / (1024 ** 3),
                self.precision,
                self.concurrent,
            )
        except Exception as exc:
            self.cpu_only = True
            self.device = "cpu"
            self.precision = "fp32"
            logger.warning("Failed to query GPU properties: %s. Falling back to CPU.", exc)

    @property
    def loaded_model_names(self) -> list[str]:
        """List names of currently loaded models.

        Returns:
            List of model name strings.
        """
        return list(self._loaded_models.keys())

    def _get_vram_used(self) -> int:
        """Get current VRAM usage in bytes.

        Returns:
            VRAM allocated in bytes, or 0 if in CPU mode.
        """
        if self.cpu_only:
            return 0
        try:
            import torch
            device_index = 0
            if ":" in self.device:
                try:
                    device_index = int(self.device.split(":")[1])
                except (ValueError, IndexError):
                    device_index = 0
            return torch.cuda.memory_allocated(device_index)
        except Exception:
            return 0

    def _get_vram_free(self) -> int:
        """Get available VRAM in bytes.

        Returns:
            Free VRAM in bytes.
        """
        if self.cpu_only or self._vram_total == 0:
            return 0
        return max(0, self._vram_total - self._get_vram_used())

    def _evict_lru(self, needed_bytes: int) -> None:
        """Evict least-recently-used models to free VRAM.

        Args:
            needed_bytes: Bytes of VRAM that need to be freed.
        """
        freed = 0
        to_evict: list[str] = []

        for name, entry in self._loaded_models.items():
            if freed >= needed_bytes:
                break
            to_evict.append(name)
            freed += entry.vram_estimate_bytes

        for name in to_evict:
            logger.info("Evicting LRU model: %s", name)
            self.unload(name)

    def load(
        self,
        model_name: str,
        loader_fn: object | None = None,
        vram_estimate_bytes: int = 0,
    ) -> object:
        """Load a model, evicting LRU models if VRAM is tight.

        If the model is already loaded, moves it to the end of the LRU
        queue and returns it.

        Args:
            model_name: Unique identifier for the model.
            loader_fn: Callable that returns the loaded model.
                Must be provided if the model is not already loaded.
            vram_estimate_bytes: Estimated VRAM consumption of this model.

        Returns:
            The loaded model object.

        Raises:
            GPUError: If the model cannot be loaded and no loader was provided.
        """
        if model_name in self._loaded_models:
            entry = self._loaded_models[model_name]
            self._loaded_models.move_to_end(model_name)
            logger.debug("Model %s already loaded, moved to MRU.", model_name)
            return entry.model

        if loader_fn is None:
            raise GPUError(
                f"Model {model_name} is not loaded and no loader_fn was provided.",
                details={"model_name": model_name},
            )

        # If not in concurrent mode, unload all other models first
        if not self.concurrent and self._loaded_models:
            logger.info(
                "Sequential mode: unloading %d models before loading %s",
                len(self._loaded_models),
                model_name,
            )
            for name in list(self._loaded_models.keys()):
                self.unload(name)

        # In concurrent mode, check if we need to evict
        if self.concurrent and vram_estimate_bytes > 0:
            free = self._get_vram_free()
            if free < vram_estimate_bytes:
                self._evict_lru(vram_estimate_bytes - free)

        try:
            if callable(loader_fn):
                model = loader_fn()
            else:
                raise GPUError(
                    f"loader_fn for model {model_name} is not callable.",
                    details={"model_name": model_name},
                )
        except GPUError:
            raise
        except Exception as exc:
            raise GPUError(
                f"Failed to load model {model_name}: {exc}",
                details={"model_name": model_name},
            ) from exc

        self._loaded_models[model_name] = _ModelEntry(
            name=model_name,
            model=model,
            vram_estimate_bytes=vram_estimate_bytes,
        )
        logger.info("Loaded model: %s (est. %.1f MB VRAM)", model_name, vram_estimate_bytes / (1024 ** 2))
        return model

    def unload(self, model_name: str) -> None:
        """Unload a model and free its VRAM.

        Args:
            model_name: Identifier of the model to unload.
        """
        entry = self._loaded_models.pop(model_name, None)
        if entry is None:
            logger.debug("Model %s not loaded, nothing to unload.", model_name)
            return

        # Release the reference
        del entry.model
        del entry

        # Trigger CUDA garbage collection if available
        if not self.cpu_only:
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass

        logger.info("Unloaded model: %s", model_name)

    def unload_all(self) -> None:
        """Unload all currently loaded models."""
        for name in list(self._loaded_models.keys()):
            self.unload(name)

    def get_health(self) -> GPUHealthReport:
        """Generate a health report of the current GPU state.

        Returns:
            GPUHealthReport with current device info and VRAM usage.
        """
        if self.cpu_only:
            return GPUHealthReport(
                device_name="CPU",
                compute_capability="N/A",
                vram_total_bytes=0,
                vram_used_bytes=0,
                vram_free_bytes=0,
                precision=self.precision,
                concurrent_mode=False,
                loaded_models=self.loaded_model_names,
                cpu_only=True,
            )

        device_name = "Unknown GPU"
        cc = "N/A"
        vram_used = self._get_vram_used()

        try:
            import torch
            device_index = 0
            if ":" in self.device:
                try:
                    device_index = int(self.device.split(":")[1])
                except (ValueError, IndexError):
                    device_index = 0
            props = torch.cuda.get_device_properties(device_index)
            device_name = props.name
            cc_val = get_compute_capability(device_index)
            cc = cc_val if cc_val is not None else "N/A"
        except Exception as exc:
            logger.warning("Failed to query GPU properties for health report: %s", exc)

        return GPUHealthReport(
            device_name=device_name,
            compute_capability=cc,
            vram_total_bytes=self._vram_total,
            vram_used_bytes=vram_used,
            vram_free_bytes=max(0, self._vram_total - vram_used),
            precision=self.precision,
            concurrent_mode=self.concurrent,
            loaded_models=self.loaded_model_names,
            cpu_only=False,
        )

    def is_model_loaded(self, model_name: str) -> bool:
        """Check if a model is currently loaded.

        Args:
            model_name: Model identifier to check.

        Returns:
            True if the model is loaded, False otherwise.
        """
        return model_name in self._loaded_models

    def get_model(self, model_name: str) -> object | None:
        """Get a loaded model by name without affecting LRU order.

        Args:
            model_name: Model identifier.

        Returns:
            The model object if loaded, None otherwise.
        """
        entry = self._loaded_models.get(model_name)
        return entry.model if entry is not None else None
