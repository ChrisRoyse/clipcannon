"""Rendering MCP tool: clipcannon_get_scene_map."""

from __future__ import annotations

import json

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.rendering_common import _db_path, _error, _project_dir


# ============================================================
# TOOL 5: clipcannon_get_scene_map
# ============================================================
async def clipcannon_get_scene_map(
    project_id: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    detail: str = "summary",
    layout: str | None = None,
) -> dict[str, object]:
    """Get the scene map with pagination and detail control.

    Supports two detail modes for bounded token output:
    - **summary** (~40 tokens/scene): id, start/end, layout,
      has_face, transcript preview (first 80 chars).
    - **full** (~120 tokens/scene): all fields including
      canvas_regions, but only for the requested layout.

    Time-window pagination keeps each response bounded. Default
    window is 5 minutes from *start_ms*.

    Args:
        project_id: Project identifier.
        start_ms: Window start in milliseconds (default 0).
        end_ms: Window end in milliseconds (default start_ms + 300000).
        detail: ``"summary"`` or ``"full"`` (default ``"summary"``).
        layout: Layout to return — ``"A"``, ``"B"``, ``"C"``, ``"D"``,
            or ``None`` for the scene's recommended layout only.
    """
    # ---- validate detail param ----
    if detail not in ("summary", "full"):
        return _error(
            "INVALID_PARAMETER",
            f"detail must be 'summary' or 'full', got '{detail}'",
        )

    # ---- validate layout param ----
    valid_layouts = {"A", "B", "C", "D"}
    if layout is not None and layout not in valid_layouts:
        return _error(
            "INVALID_PARAMETER",
            f"layout must be one of A/B/C/D or null, got '{layout}'",
        )

    # ---- compute window ----
    if end_ms is None:
        end_ms = start_ms + 300_000  # 5-minute default window

    if end_ms <= start_ms:
        return _error(
            "INVALID_PARAMETER",
            f"end_ms ({end_ms}) must be greater than start_ms ({start_ms})",
        )

    proj_dir = _project_dir(project_id)
    if not proj_dir.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )

    db = _db_path(project_id)
    if not db.exists():
        return _error("DB_NOT_FOUND", "Project database not found")

    conn = get_connection(str(db), enable_vec=False, dict_rows=True)
    try:
        # Get project info
        proj = fetch_one(
            conn,
            "SELECT resolution, duration_ms, fps FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error(
                "PROJECT_NOT_FOUND",
                f"No project record: {project_id}",
            )

        # Total scene count (whole project)
        total_row = fetch_one(
            conn,
            "SELECT COUNT(*) AS cnt FROM scene_map "
            "WHERE project_id = ?",
            (project_id,),
        )
        total_scenes_in_project = int(total_row["cnt"]) if total_row else 0

        # Windowed scene query
        scenes_raw = fetch_all(
            conn,
            "SELECT * FROM scene_map WHERE project_id = ? "
            "AND start_ms >= ? AND start_ms < ? ORDER BY start_ms",
            (project_id, start_ms, end_ms),
        )

        # Check if more scenes exist beyond window
        next_row = fetch_one(
            conn,
            "SELECT MIN(start_ms) AS next_ms FROM scene_map "
            "WHERE project_id = ? AND start_ms >= ?",
            (project_id, end_ms),
        )

        # Batch-fetch text_change_events and emotion_curve for summary enrichment
        _text_changes: list[dict[str, object]] = []
        _emotion_entries: list[dict[str, object]] = []
        if detail == "summary" and scenes_raw:
            try:
                _text_changes = [
                    dict(r)
                    for r in fetch_all(
                        conn,
                        "SELECT timestamp_ms, new_title FROM text_change_events "
                        "WHERE project_id = ? AND timestamp_ms >= ? AND timestamp_ms < ? "
                        "ORDER BY timestamp_ms",
                        (project_id, start_ms, end_ms),
                    )
                ]
            except Exception:
                _text_changes = []
            try:
                _emotion_entries = [
                    dict(r)
                    for r in fetch_all(
                        conn,
                        "SELECT start_ms, end_ms, energy FROM emotion_curve "
                        "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
                        "ORDER BY start_ms",
                        (project_id, end_ms, start_ms),
                    )
                ]
            except Exception:
                _emotion_entries = []
    except Exception as exc:
        return _error(
            "SCENE_MAP_NOT_FOUND",
            f"Scene map not available. Run ingest first. Error: {exc}",
        )
    finally:
        conn.close()

    if not scenes_raw and total_scenes_in_project == 0:
        return _error(
            "SCENE_MAP_EMPTY",
            "No scenes in scene map. Run ingest first.",
        )

    has_more = next_row is not None and next_row["next_ms"] is not None
    next_start_ms = int(next_row["next_ms"]) if has_more else None

    # ---- Build response scenes ----
    scenes: list[dict[str, object]] = []
    webcam_info: dict[str, object] | None = None

    for row in scenes_raw:
        rec_layout = str(row.get("layout_recommendation", "A"))

        if detail == "summary":
            # ~120 tokens per scene: compact with storyboard context
            transcript_raw = str(row.get("transcript_text", ""))
            preview = transcript_raw[:80]
            if len(transcript_raw) > 80:
                preview += "..."

            scene_start = int(row["start_ms"])
            scene_end = int(row["end_ms"])
            scene_mid = (scene_start + scene_end) // 2

            # screen_content: most recent text_change_event at or before scene start
            screen_content = ""
            for tc in reversed(_text_changes):
                if int(tc.get("timestamp_ms", 0)) <= scene_start:
                    raw_title = str(tc.get("new_title", "") or "")
                    screen_content = raw_title[:60]
                    break

            # speaker_activity: classify from transcript text
            text_lower = transcript_raw.lower()
            screen_ref_phrases = ("you can see", "look at", "this shows", "here")
            direct_addr_words = (" i ", " you ", " we ", "let me", " i'")
            if any(p in text_lower for p in screen_ref_phrases):
                speaker_activity = "screen_reference"
            elif any(w in f" {text_lower} " for w in direct_addr_words):
                speaker_activity = "direct_address"
            else:
                speaker_activity = "narrating"

            # energy: nearest emotion_curve entry to scene midpoint
            energy: float | None = None
            best_dist = float("inf")
            for em in _emotion_entries:
                em_mid = (int(em.get("start_ms", 0)) + int(em.get("end_ms", 0))) // 2
                dist = abs(em_mid - scene_mid)
                if dist < best_dist:
                    best_dist = dist
                    energy = round(float(em.get("energy", 0)), 4)

            scene: dict[str, object] = {
                "id": int(row["scene_id"]),
                "start_ms": scene_start,
                "end_ms": scene_end,
                "layout": rec_layout,
                "has_face": row.get("face_x") is not None,
                "transcript_preview": preview,
                "screen_content": screen_content,
                "speaker_activity": speaker_activity,
                "energy": energy,
            }
        else:
            # full mode (~120 tokens per scene)
            scene = {
                "id": int(row["scene_id"]),
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "duration_ms": int(row["end_ms"]) - int(row["start_ms"]),
                "transcript": str(row.get("transcript_text", "")),
                "layout": rec_layout,
            }

            # Face
            if row.get("face_x") is not None:
                scene["face"] = {
                    "x": int(row["face_x"]),
                    "y": int(row["face_y"]),
                    "w": int(row["face_w"]),
                    "h": int(row["face_h"]),
                    "conf": float(row.get("face_confidence") or 0),
                }

            # Content region
            if row.get("content_x") is not None:
                scene["content"] = {
                    "x": int(row["content_x"]),
                    "y": int(row["content_y"]),
                    "w": int(row["content_w"]),
                    "h": int(row["content_h"]),
                }

            # Canvas regions — only the requested layout
            canvas_json = str(row.get("canvas_regions_json", "{}"))
            try:
                all_canvas = json.loads(canvas_json)
            except (json.JSONDecodeError, TypeError):
                all_canvas = {}

            target_layout = layout if layout is not None else rec_layout
            if isinstance(all_canvas, dict) and target_layout in all_canvas:
                scene["canvas"] = {target_layout: all_canvas[target_layout]}
            else:
                scene["canvas"] = {}

        scenes.append(scene)

        # Extract webcam info from first scene that has it
        if webcam_info is None and row.get("webcam_x") is not None:
            webcam_info = {
                "detected": True,
                "x": int(row["webcam_x"]),
                "y": int(row["webcam_y"]),
                "w": int(row["webcam_w"]),
                "h": int(row["webcam_h"]),
            }

    response: dict[str, object] = {
        "project_id": project_id,
        "source": {
            "resolution": str(proj["resolution"]),
            "duration_ms": int(proj["duration_ms"]),
            "fps": float(proj["fps"]),
        },
        "webcam": webcam_info or {"detected": False},
        "window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        "total_scenes_in_window": len(scenes),
        "total_scenes_in_project": total_scenes_in_project,
        "has_more": has_more,
        "scenes": scenes,
    }
    if next_start_ms is not None:
        response["next_start_ms"] = next_start_ms

    return response
