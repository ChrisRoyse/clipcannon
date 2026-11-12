"""Mixed audio preparation for RenderEngine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all

from .helpers import _parse_sfx_offset_ms

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList

logger = logging.getLogger(__name__)


class _AudioMixMixin:
    """Mixed audio preparation (music, SFX, ducking) for RenderEngine."""

    # ----------------------------------------------------------------
    # Audio mixing
    # ----------------------------------------------------------------
    async def _prepare_mixed_audio(
        self,
        edl: EditDecisionList,
        db_path: Path,
        concat_path: Path,
        temp_dir: Path,
        render_id: str,
    ) -> Path | None:
        """Mix audio assets (music, SFX) into the concatenated audio.

        Queries audio_assets for the edit, extracts source audio from
        the concat video, calls the mixer, and returns the mixed WAV.

        Args:
            edl: EDL with edit_id for asset lookup.
            db_path: Path to the project database.
            concat_path: Path to the concatenated video.
            temp_dir: Temporary directory for intermediate files.
            render_id: Render ID for logging.

        Returns:
            Path to the mixed WAV file, or None if no audio assets.
        """
        from clipcannon.audio.mixer import mix_audio

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT asset_id, type, file_path, volume_db, "
                "generation_params "
                "FROM audio_assets WHERE edit_id = ? ORDER BY type",
                (edl.edit_id,),
            )
        finally:
            conn.close()

        if not rows:
            return None

        music_path: Path | None = None
        music_volume_db = -18.0
        cleanup_path: Path | None = None
        sfx_entries: list[dict[str, object]] = []

        for row in rows:
            asset_type = str(row["type"])
            file_path = Path(str(row["file_path"]))
            volume_db = float(row["volume_db"] or 0)

            if not file_path.exists():
                # The edit asks for this asset; rendering without it would
                # deliver a different edit than requested (#68).
                raise FileNotFoundError(
                    f"Render {render_id}: audio asset {asset_type} missing: {file_path}"
                )

            if asset_type == "music":
                # Render MIDI to WAV if needed (compose_music outputs .mid)
                if file_path.suffix.lower() in (".mid", ".midi"):
                    from clipcannon.audio.midi_render import render_midi_to_wav
                    wav_path = temp_dir / f"{file_path.stem}_rendered.wav"
                    await render_midi_to_wav(file_path, wav_path)
                    if not wav_path.exists():
                        raise RuntimeError(
                            f"Render {render_id}: MIDI render produced no WAV for {file_path}"
                        )
                    file_path = wav_path
                    logger.info("Render %s: MIDI rendered to WAV: %s", render_id, wav_path)
                music_path = file_path
                music_volume_db = volume_db
            elif asset_type == "sfx":
                offset_ms = _parse_sfx_offset_ms(
                    row["generation_params"]
                )
                sfx_entries.append({
                    "path": str(file_path),
                    "offset_ms": offset_ms,
                    "volume_db": volume_db,
                })
            elif asset_type == "cleaned":
                cleanup_path = file_path

        if music_path is None and not sfx_entries and cleanup_path is None:
            logger.debug(
                "Render %s: no audio assets found, skipping mix",
                render_id,
            )
            return None

        # Extract audio from concatenated video
        source_audio = temp_dir / "source_audio.wav"
        extract_cmd: list[str] = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "44100",
            str(source_audio),
        ]
        await self._execute_ffmpeg(
            extract_cmd, f"{render_id}_extract_audio"
        )

        if not source_audio.exists():
            logger.warning(
                "Render %s: audio extraction failed", render_id,
            )
            return None

        # Use cleanup audio as source when available
        mix_source = source_audio
        if cleanup_path is not None and cleanup_path.exists():
            logger.info(
                "Render %s: using cleaned audio as source: %s",
                render_id, cleanup_path,
            )
            mix_source = cleanup_path

        # Mix source speech with background music and SFX
        mixed_output = temp_dir / "mixed_audio.wav"
        try:
            result = await mix_audio(
                source_audio_path=mix_source,
                output_path=mixed_output,
                background_music_path=music_path,
                sfx_entries=sfx_entries or None,
                music_volume_db=music_volume_db,
                duck_under_speech=True,
            )
            logger.info(
                "Render %s: audio mixed (%d layers, %dms)",
                render_id, result.layers_mixed, result.duration_ms,
            )
        except Exception as exc:
            # Was: render on without the requested music/SFX (#68).
            raise RuntimeError(f"Render {render_id}: audio mixing failed: {exc}") from exc
        finally:
            source_audio.unlink(missing_ok=True)

        return mixed_output
