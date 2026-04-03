"""Virtual device management for clone meeting agents.

Creates and manages:
- v4l2loopback virtual webcam devices (Mode 1: Replace Me)
- PulseAudio null sink + remap source for virtual microphone

Each clone gets its own video device + audio sink/source pair.
Devices are created on start and destroyed on stop.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from voiceagent.meeting.errors import MeetingDeviceError

logger = logging.getLogger(__name__)


@dataclass
class CloneDevicePair:
    """A clone's virtual device configuration.

    Attributes:
        clone_name: Identifier for the clone (e.g. "nate").
        video_device: Path to v4l2loopback device (e.g. "/dev/video20").
        video_label: Human-readable label shown in meeting apps.
        audio_sink: PulseAudio null-sink name for TTS output.
        audio_source: PulseAudio remap-source name (appears as mic).
        pulse_sink_module: PulseAudio module ID for sink (for cleanup).
        pulse_source_module: PulseAudio module ID for source (for cleanup).
    """

    clone_name: str
    video_device: str
    video_label: str
    audio_sink: str
    audio_source: str
    pulse_sink_module: int | None = None
    pulse_source_module: int | None = None


class CloneDeviceManager:
    """Create and destroy virtual webcam + mic pairs for clones.

    Video: v4l2loopback kernel module (must be loaded with modprobe).
    Audio: PulseAudio null-sink + module-remap-source.
    """

    def __init__(self) -> None:
        self._devices: dict[str, CloneDevicePair] = {}

    def create_audio_devices(self, clone_name: str) -> CloneDevicePair:
        """Create PulseAudio virtual mic for a clone.

        Creates:
            1. null-sink named clone_{name}_sink
            2. remap-source named clone_{name}_mic (so apps see it as a
               mic, not a monitor)

        Args:
            clone_name: Unique identifier for the clone.

        Returns:
            CloneDevicePair with audio device info populated.

        Raises:
            MeetingDeviceError: If pactl commands fail or pactl is not
                installed.
        """
        sink_name = f"clone_{clone_name}_sink"
        source_name = f"clone_{clone_name}_mic"
        label = f"Clone {clone_name.title()}"

        # Create null sink
        try:
            result = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={sink_name}",
                    f"sink_properties=device.description={label}_Audio",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise MeetingDeviceError(
                    f"Failed to create PulseAudio sink '{sink_name}': "
                    f"{result.stderr}"
                )
            sink_module = (
                int(result.stdout.strip())
                if result.stdout.strip().isdigit()
                else None
            )
        except FileNotFoundError:
            raise MeetingDeviceError(
                "pactl not found. Install PulseAudio: "
                "apt install pulseaudio-utils"
            )
        except subprocess.TimeoutExpired:
            raise MeetingDeviceError(
                "pactl timed out creating null sink"
            )

        # Create remap source (makes monitor appear as a real mic)
        try:
            result = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-remap-source",
                    f"master={sink_name}.monitor",
                    f"source_name={source_name}",
                    f"source_properties=device.description={label}_Mic",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise MeetingDeviceError(
                    f"Failed to create remap source '{source_name}': "
                    f"{result.stderr}"
                )
            source_module = (
                int(result.stdout.strip())
                if result.stdout.strip().isdigit()
                else None
            )
        except subprocess.TimeoutExpired:
            raise MeetingDeviceError(
                "pactl timed out creating remap source"
            )

        # Assign v4l2loopback device number based on active device count
        video_nr = 20 + len(self._devices)
        video_device = f"/dev/video{video_nr}"

        pair = CloneDevicePair(
            clone_name=clone_name,
            video_device=video_device,
            video_label=label,
            audio_sink=sink_name,
            audio_source=source_name,
            pulse_sink_module=sink_module,
            pulse_source_module=source_module,
        )
        self._devices[clone_name] = pair
        logger.info(
            "Created audio devices for %s: sink=%s, source=%s",
            clone_name,
            sink_name,
            source_name,
        )
        return pair

    def destroy_audio_devices(self, clone_name: str) -> None:
        """Destroy PulseAudio virtual devices for a clone.

        Args:
            clone_name: Identifier of the clone whose devices to destroy.
        """
        pair = self._devices.pop(clone_name, None)
        if pair is None:
            return

        # Unload modules in reverse order (source first, then sink)
        for module_id in [pair.pulse_source_module, pair.pulse_sink_module]:
            if module_id is not None:
                try:
                    subprocess.run(
                        ["pactl", "unload-module", str(module_id)],
                        capture_output=True,
                        timeout=10,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
        logger.info("Destroyed audio devices for %s", clone_name)

    def destroy_all(self) -> None:
        """Destroy all virtual devices for all clones."""
        for name in list(self._devices.keys()):
            self.destroy_audio_devices(name)

    def list_active(self) -> list[CloneDevicePair]:
        """List all active clone device pairs.

        Returns:
            List of CloneDevicePair for each active clone.
        """
        return list(self._devices.values())

    @staticmethod
    def check_v4l2loopback() -> bool:
        """Check if v4l2loopback kernel module is loaded.

        Returns:
            True if the module is loaded, False otherwise.
        """
        try:
            result = subprocess.run(
                ["lsmod"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "v4l2loopback" in result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
