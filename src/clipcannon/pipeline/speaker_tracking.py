"""Pipeline stage: face tracks, active speakers and who-said-what turns.

Runs three GPU workers as subprocesses (face_worker -> asd_worker,
voice_worker), then binds face, voice and transcript per segment
(speaker_turns) and persists:

    face_shots         hard-cut shots
    face_tracks        face tracks with their person and mean speaking score
    face_detections    10 fps boxes + speaking logit per tracked face
    persons            identity clusters (label is editable)
    speaker_segments   speaker per transcript segment, with the evidence used
    speaker_turns      merged turns: speaker, on-screen time, text, keywords

The render path uses face_detections + speaker_segments to frame the active
speaker (editing/speaker_framing.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import subprocess
import time
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "speaker_tracking"
STAGE = "speaker_tracking"

SCHEMA = """
CREATE TABLE IF NOT EXISTS face_shots (
    project_id TEXT NOT NULL, shot_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
    PRIMARY KEY (project_id, shot_id));
CREATE TABLE IF NOT EXISTS face_tracks (
    project_id TEXT NOT NULL, track_id INTEGER NOT NULL, shot_id INTEGER NOT NULL,
    person_id INTEGER, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
    median_height REAL, mean_asd REAL, speaking_frac REAL,
    PRIMARY KEY (project_id, track_id));
CREATE TABLE IF NOT EXISTS face_detections (
    project_id TEXT NOT NULL, t_ms INTEGER NOT NULL, track_id INTEGER NOT NULL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL, asd REAL);
CREATE INDEX IF NOT EXISTS idx_face_det_t ON face_detections(project_id, t_ms);
CREATE TABLE IF NOT EXISTS persons (
    project_id TEXT NOT NULL, person_id INTEGER NOT NULL, label TEXT,
    frames INTEGER, speaking_ms INTEGER DEFAULT 0, voice_cluster INTEGER,
    thumb_t_ms INTEGER, thumb_x1 REAL, thumb_y1 REAL, thumb_x2 REAL, thumb_y2 REAL,
    PRIMARY KEY (project_id, person_id));
CREATE TABLE IF NOT EXISTS speaker_segments (
    project_id TEXT NOT NULL, segment_id INTEGER NOT NULL, start_ms INTEGER, end_ms INTEGER,
    person_id INTEGER, voice_cluster INTEGER, on_screen INTEGER, source TEXT,
    face_score REAL, PRIMARY KEY (project_id, segment_id));
CREATE TABLE IF NOT EXISTS speaker_turns (
    project_id TEXT NOT NULL, turn_id INTEGER NOT NULL, start_ms INTEGER, end_ms INTEGER,
    person_id INTEGER, voice_cluster INTEGER, speaker_key TEXT, on_screen_ms INTEGER,
    text TEXT, keywords TEXT, segment_ids TEXT, is_question INTEGER,
    PRIMARY KEY (project_id, turn_id));
"""

_TABLES = ("face_shots", "face_tracks", "face_detections", "persons",
           "speaker_segments", "speaker_turns")


def _run_worker(module: str, args: list[str], log_path: Path) -> dict[str, object]:
    from clipcannon.paths import resolve_ml_python

    py = resolve_ml_python()
    with open(log_path, "a") as log:
        proc = subprocess.run([py, "-m", module, *args], stdout=subprocess.PIPE,
                              stderr=log, text=True, check=False)
    if proc.returncode != 0:
        tail = log_path.read_text(errors="replace")[-1500:]
        raise RuntimeError(f"{module} failed (rc={proc.returncode}): {tail}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _persist(db_path: Path, project_id: str, fa: object, z: dict[str, np.ndarray],
             asd: np.ndarray, speakers: list, turns: list, binding: dict[int, int]) -> int:
    t = fa.frame_t_ms  # type: ignore[attr-defined]
    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(SCHEMA)
        for tbl in _TABLES:
            con.execute(f"DELETE FROM {tbl} WHERE project_id = ?", (project_id,))
        con.executemany("INSERT INTO face_shots VALUES (?,?,?,?)", [
            (project_id, i, int(t[a]), int(t[b]) + 100)
            for i, (a, b) in enumerate(fa.shots)])  # type: ignore[attr-defined]
        trows, drows = [], []
        for tr in fa.tracks:  # type: ignore[attr-defined]
            sc = asd[tr.dets]
            sc = sc[np.isfinite(sc)]
            trows.append((project_id, tr.track_id, tr.shot_id, tr.person_id,
                          int(t[tr.frames[0]]), int(t[tr.frames[-1]]) + 100,
                          tr.median_height, float(sc.mean()) if len(sc) else None,
                          float(np.mean(sc > 0)) if len(sc) else None))
            for f, d in zip(tr.frames, tr.dets, strict=True):
                b = z["det_bbox"][d]
                a = asd[d]
                drows.append((project_id, int(t[f]), tr.track_id, float(b[0]), float(b[1]),
                              float(b[2]), float(b[3]), float(a) if np.isfinite(a) else None))
        con.executemany("INSERT INTO face_tracks VALUES (?,?,?,?,?,?,?,?,?)", trows)
        con.executemany("INSERT INTO face_detections VALUES (?,?,?,?,?,?,?,?)", drows)

        speaking: dict[int, int] = {}
        for sp in speakers:
            if sp.person_id is not None:
                speaking[sp.person_id] = speaking.get(sp.person_id, 0) + sp.end_ms - sp.start_ms
        voice_of = {p: v for v, p in binding.items()}
        prows = []
        for pid, info in fa.persons.items():  # type: ignore[attr-defined]
            best = max((fa.tracks[i] for i in info["tracks"]),  # type: ignore[attr-defined]
                       key=lambda tr: tr.median_height)
            d = best.dets[len(best.dets) // 2]
            b = z["det_bbox"][d]
            prows.append((project_id, pid, None, int(info["frames"]), speaking.get(pid, 0),
                          voice_of.get(pid), int(t[z["det_frame"][d]]),
                          float(b[0]), float(b[1]), float(b[2]), float(b[3])))
        con.executemany("INSERT INTO persons VALUES (?,?,?,?,?,?,?,?,?,?,?)", prows)
        con.executemany("INSERT INTO speaker_segments VALUES (?,?,?,?,?,?,?,?,?)", [
            (project_id, sp.segment_id, sp.start_ms, sp.end_ms, sp.person_id, sp.voice_cluster,
             int(sp.on_screen), sp.source, sp.face_score) for sp in speakers])
        con.executemany("INSERT INTO speaker_turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            (project_id, tu.turn_id, tu.start_ms, tu.end_ms, tu.person_id, tu.voice_cluster,
             tu.speaker_key, tu.on_screen_ms, tu.text, json.dumps(tu.keywords),
             json.dumps(tu.segment_ids), int(tu.is_question)) for tu in turns])
        con.commit()
        return len(drows)
    finally:
        con.close()


def _segments(db_path: Path, project_id: str) -> list[tuple[int, int, int, str]]:
    con = sqlite3.connect(str(db_path))
    try:
        return [(int(a), int(b), int(c), str(d)) for a, b, c, d in con.execute(
            "SELECT segment_id, start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms", (project_id,))]
    finally:
        con.close()


def _process(project_id: str, db_path: Path, project_dir: Path) -> dict[str, object]:
    from clipcannon.pipeline.face_tracking import analyze
    from clipcannon.pipeline.speaker_turns import assign_speakers, build_turns

    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("SELECT source_path FROM project WHERE project_id = ?",
                          (project_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise RuntimeError(f"project {project_id} not found")
    source = str(row[0])
    work = project_dir / "faces"
    work.mkdir(exist_ok=True)
    log = work / "workers.log"
    faces_npz, asd_npz = work / "faces.npz", work / "asd.npz"
    voice_npz, segs_json = work / "voice.npz", work / "segments.json"

    stats: dict[str, object] = {}
    stats["faces"] = _run_worker("clipcannon.pipeline.face_worker",
                                 [source, str(faces_npz)], log)
    stats["asd"] = _run_worker("clipcannon.pipeline.asd_worker",
                               [source, str(faces_npz), str(asd_npz)], log)
    segs = _segments(db_path, project_id)
    segs_json.write_text(json.dumps([[s, e] for _, s, e, _ in segs]))
    stats["voice"] = _run_worker("clipcannon.pipeline.voice_worker",
                                 [source, str(segs_json), str(voice_npz)], log)

    z = dict(np.load(faces_npz))
    asd = np.load(asd_npz)["det_asd"]
    voice = np.load(voice_npz)
    fa = analyze(z)
    emb = voice["voice_emb"].copy()
    emb[~voice["voice_valid"]] = 0.0
    speakers, binding = assign_speakers(fa, z["det_frame"], asd, segs, emb)
    turns = build_turns(speakers)
    n = _persist(db_path, project_id, fa, z, asd, speakers, turns, binding)
    stats.update({"shots": len(fa.shots), "tracks": len(fa.tracks),
                  "persons": len(fa.persons), "detections": n, "turns": len(turns),
                  "voice_bindings": {str(k): v for k, v in binding.items()},
                  "segments_attributed": sum(sp.person_id is not None for sp in speakers),
                  "segments_total": len(speakers)})
    return stats


async def run_speaker_tracking(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the speaker tracking stage."""
    start = time.monotonic()
    try:
        stats = await asyncio.to_thread(_process, project_id, db_path, project_dir)
    except Exception as exc:
        logger.exception("Speaker tracking failed")
        return StageResult(success=False, operation=OPERATION, error_message=str(exc))
    elapsed_ms = int((time.monotonic() - start) * 1000)
    summary = json.dumps(stats, sort_keys=True)
    record_id = record_provenance(
        db_path=db_path, project_id=project_id, operation=OPERATION, stage=STAGE,
        input_info=InputInfo(sha256=sha256_string(f"speaker-tracking-{project_id}")),
        output_info=OutputInfo(sha256=sha256_string(summary),
                               record_count=int(stats.get("detections", 0))),
        model_info=ModelInfo(name="insightface-buffalo_l+light-asd+ecapa-voxceleb",
                             version="buffalo_l/pretrain_AVA_CVPR/spkrec-ecapa-voxceleb"),
        execution_info=ExecutionInfo(duration_ms=elapsed_ms),
        parent_record_id=None,
        description=f"Speaker tracking: {summary}",
    )
    logger.info("Speaker tracking complete in %d ms: %s", elapsed_ms, summary)
    return StageResult(success=True, operation=OPERATION, duration_ms=elapsed_ms,
                       provenance_record_id=record_id)
