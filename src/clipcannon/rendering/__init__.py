"""Rendering package for ClipCannon Phase 2.

Provides the rendering engine, encoding profiles, batch rendering,
and thumbnail generation for converting EDLs into platform-ready
video files.
"""

from clipcannon.rendering.batch import render_batch
from clipcannon.rendering.profiles import (
    EncodingProfile,
    get_profile,
    get_software_fallback,
    list_profiles,
)
from clipcannon.rendering.renderer import RenderEngine, RenderResult
from clipcannon.rendering.thumbnail import generate_thumbnail

__all__ = [
    "EncodingProfile",
    "RenderEngine",
    "RenderResult",
    "generate_thumbnail",
    "get_profile",
    "get_software_fallback",
    "list_profiles",
    "render_batch",
]
