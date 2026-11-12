"""Regression tests: the render inspector must compare bitstream codecs, not
encoder names (h264_nvenc renders were reported as codec_match=False)."""
from __future__ import annotations

import pytest

from clipcannon.rendering.inspector import normalize_codec_name


@pytest.mark.parametrize(
    ("encoder", "codec"),
    [
        ("h264_nvenc", "h264"),
        ("libx264", "h264"),
        ("h264", "h264"),
        ("hevc_nvenc", "hevc"),
        ("libx265", "hevc"),
        ("h265", "hevc"),
        ("hevc", "hevc"),
        ("av1_nvenc", "av1"),
        ("libsvtav1", "av1"),
        ("h264_qsv", "h264"),
        ("hevc_vaapi", "hevc"),
        ("H264_NVENC", "h264"),
        ("libvpx-vp9", "vp9"),
    ],
)
def test_encoder_normalizes_to_codec(encoder: str, codec: str) -> None:
    assert normalize_codec_name(encoder) == codec


def test_different_codecs_still_mismatch() -> None:
    assert normalize_codec_name("h264_nvenc") != normalize_codec_name("hevc")
    assert normalize_codec_name("libx265") != normalize_codec_name("h264")


def test_unknown_codec_passes_through() -> None:
    assert normalize_codec_name("mpeg4") == "mpeg4"
