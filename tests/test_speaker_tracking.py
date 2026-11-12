"""Tests for face tracking, speaker attribution, speaker framing and the
tracked-framing FFmpeg chain."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.editing.edl import (
    SegmentCanvasSpec,
    SegmentSpec,
    TrackedFraming,
    TrackedPiece,
)
from clipcannon.pipeline.face_tracking import analyze, build_tracks, detect_shots
from clipcannon.pipeline.speaker_tracking import SCHEMA
from clipcannon.pipeline.speaker_turns import assign_speakers, build_turns


# ------------------------------------------------------------------ synthetic world
def _world() -> dict[str, np.ndarray]:
    """20 s at 10 fps. Shot A (0-10 s): persons X (left) and Y (right), both
    visible. Shot B (10-20 s): close-up of Y only."""
    rng = np.random.default_rng(0)
    n = 200
    hist = np.zeros((n, 48), np.float32)
    hist[:100, :24] = 1 / 24
    hist[100:, 24:] = 1 / 24
    ex = rng.normal(size=512)
    ey = rng.normal(size=512)
    ex /= np.linalg.norm(ex)
    ey /= np.linalg.norm(ey)
    frames, boxes, emb, has = [], [], [], []
    for f in range(n):
        if f < 100:
            for cx, e in ((480, ex), (1440, ey)):
                frames.append(f)
                boxes.append([cx - 40, 400, cx + 40, 500])
                emb.append(e + rng.normal(scale=0.05, size=512))
                has.append(f % 5 == 0)
        else:
            frames.append(f)
            boxes.append([800, 200, 1100, 560])
            emb.append(ey + rng.normal(scale=0.05, size=512))
            has.append(f % 5 == 0)
    emb_a = np.array(emb, np.float32)
    emb_a /= np.linalg.norm(emb_a, axis=1, keepdims=True)
    d = len(frames)
    return {
        "frame_t_ms": np.arange(n, dtype=np.int64) * 100,
        "frame_hist": hist,
        "det_frame": np.array(frames, np.int32),
        "det_bbox": np.array(boxes, np.float32),
        "det_score": np.ones(d, np.float32),
        "det_mouth": rng.uniform(0, 0.1, d).astype(np.float32),
        "det_emb": emb_a.astype(np.float16),
        "det_has_emb": np.array(has, bool),
        "source_size": np.array([1920, 1080], np.int32),
        "fps": np.array([10.0], np.float32),
    }


def _asd_for(z: dict[str, np.ndarray], speaker_x: float | None, t0: int, t1: int) -> np.ndarray:
    """Speaking logits: the face centred at speaker_x speaks during [t0, t1) frames."""
    asd = np.full(len(z["det_frame"]), -2.0, np.float32)
    cx = (z["det_bbox"][:, 0] + z["det_bbox"][:, 2]) / 2
    if speaker_x is not None:
        hit = (np.abs(cx - speaker_x) < 1) & (z["det_frame"] >= t0) & (z["det_frame"] < t1)
        asd[hit] = 1.5
    return asd


# ------------------------------------------------------------------ face tracking
class TestFaceTracking:
    def test_detects_the_cut(self) -> None:
        shot_of, shots = detect_shots(_world()["frame_hist"])
        assert shots == [(0, 99), (100, 199)]
        assert shot_of[99] == 0 and shot_of[100] == 1

    def test_tracks_never_cross_a_cut(self) -> None:
        z = _world()
        shot_of, _ = detect_shots(z["frame_hist"])
        tracks, _ = build_tracks(z["det_frame"], z["det_bbox"], shot_of)
        assert len(tracks) == 3
        for tr in tracks:
            assert len({int(shot_of[f]) for f in tr.frames}) == 1

    def test_same_face_in_two_shots_is_one_person(self) -> None:
        fa = analyze(_world())
        assert len(fa.persons) == 2
        by_shot = {(tr.shot_id, int(np.median(fa.track_of_det[tr.dets]))): tr.person_id
                   for tr in fa.tracks}
        y_wide = next(tr.person_id for tr in fa.tracks
                      if tr.shot_id == 0 and fa.source_size and
                      _world()["det_bbox"][tr.dets[0], 0] > 1000)
        y_close = next(tr.person_id for tr in fa.tracks if tr.shot_id == 1)
        assert y_wide == y_close
        assert by_shot  # tracks exist in both shots


# ------------------------------------------------------------------ speaker attribution
class TestSpeakerAttribution:
    def test_face_evidence_picks_the_talking_face(self) -> None:
        z = _world()
        fa = analyze(z)
        asd = _asd_for(z, 480, 0, 100)                       # X talks in the wide shot
        segs = [(1, 0, 9_000, "hello from the left"), (2, 12_000, 18_000, "")]
        sp, _ = assign_speakers(fa, z["det_frame"], asd, segs)
        x = next(tr.person_id for tr in fa.tracks if z["det_bbox"][tr.dets[0], 0] < 600)
        assert sp[0].person_id == x and sp[0].on_screen and sp[0].source == "face"
        assert sp[1].person_id is None                        # nobody's lips move

    def test_voice_binding_names_the_speaker_when_face_evidence_is_absent(self) -> None:
        z = _world()
        fa = analyze(z)
        asd = _asd_for(z, 1440, 0, 100)                      # Y talks in the wide shot
        rng = np.random.default_rng(1)
        vy = rng.normal(size=192)
        vy /= np.linalg.norm(vy)
        segs = [(1, 0, 3_000, "a"), (2, 3_000, 6_000, "b"), (3, 6_000, 9_500, "c"),
                (4, 12_000, 18_000, "d")]                    # 4: close-up, ASD says no
        voice = np.stack([vy + rng.normal(scale=0.02, size=192) for _ in segs])
        sp, binding = assign_speakers(fa, z["det_frame"], asd, segs, voice)
        y = sp[0].person_id
        assert y is not None and binding and list(binding.values()) == [y]
        assert sp[3].person_id == y and sp[3].source == "voice"

    def test_unbound_voice_stays_anonymous(self) -> None:
        z = _world()
        fa = analyze(z)
        asd = _asd_for(z, None, 0, 0)                         # nobody visibly speaks
        rng = np.random.default_rng(2)
        v = rng.normal(size=192)
        voice = np.stack([v / np.linalg.norm(v)] * 2)
        segs = [(1, 0, 4_000, "Okay, next question."), (2, 4_000, 8_000, "Go ahead.")]
        sp, binding = assign_speakers(fa, z["det_frame"], asd, segs, voice)
        assert binding == {}
        assert all(s.person_id is None and s.voice_cluster == 0 for s in sp)
        turns = build_turns(sp)
        assert len(turns) == 1 and turns[0].speaker_key == "V0"

    def test_turns_merge_and_carry_keywords(self) -> None:
        z = _world()
        fa = analyze(z)
        asd = _asd_for(z, 480, 0, 100)
        segs = [(1, 0, 4_000, "The Orion heat shield performed well."),
                (2, 4_200, 9_000, "Heat shield data looks great, the heat shield held."),
                (3, 12_000, 18_000, "Is that right?")]
        turns = build_turns(assign_speakers(fa, z["det_frame"], asd, segs)[0])
        assert turns[0].segment_ids == [1, 2]
        assert "heat shield" in turns[0].keywords
        assert turns[-1].is_question


# ------------------------------------------------------------------ framing
def _db_with(tmp_path: Path, z: dict[str, np.ndarray], speaker_x: float) -> Path:
    from clipcannon.pipeline.speaker_tracking import _persist

    fa = analyze(z)
    asd = _asd_for(z, speaker_x, 0, 200)
    segs = [(1, 0, 9_900, "left talks"), (2, 10_000, 19_900, "close-up talks")]
    sp, binding = assign_speakers(fa, z["det_frame"], asd, segs)
    db = tmp_path / "analysis.db"
    _persist(db, "p", fa, z, asd, sp, build_turns(sp), binding)
    return db


class TestSpeakerFraming:
    def test_frames_the_speaker_not_the_centre(self, tmp_path: Path) -> None:
        from clipcannon.editing.speaker_framing import compute_tracked_framing

        z = _world()
        db = _db_with(tmp_path, z, 480)                      # left person speaks
        fr = compute_tracked_framing(db, "p", 0, 10_000, source_size=(1920, 1080),
                                     canvas_size=(1080, 1920))
        assert fr is not None and len(fr.pieces) == 1
        p = fr.pieces[0]
        assert p.height / p.width == pytest.approx(1920 / 1080, rel=0.02)
        for _t, x, _y in p.keyframes:
            assert x <= 480 <= x + p.width                  # speaker inside the window
            assert x + p.width < 1440 - 40                  # other person outside

    def test_one_piece_per_shot_and_exact_tiling(self, tmp_path: Path) -> None:
        from clipcannon.editing.speaker_framing import compute_tracked_framing

        z = _world()
        db = _db_with(tmp_path, z, 480)
        fr = compute_tracked_framing(db, "p", 2_350, 17_650, source_size=(1920, 1080),
                                     canvas_size=(1080, 1920))
        assert fr is not None and len(fr.pieces) == 2
        assert fr.pieces[0].start_ms == 2_350 and fr.pieces[-1].end_ms == 17_650
        assert fr.pieces[0].end_ms == fr.pieces[1].start_ms == 10_000
        assert fr.pieces[1].height == 1080                 # close-up: no zoom needed

    def test_pause_frames_the_next_speaker_not_another_face(self, tmp_path: Path) -> None:
        """At a cut into a wide shot during a pause, frame who is about to speak."""
        from clipcannon.editing.speaker_framing import compute_tracked_framing

        z = _world()
        db = _db_with(tmp_path, z, 480)
        fa = analyze(z)
        right = next(tr.person_id for tr in fa.tracks if z["det_bbox"][tr.dets[0], 0] > 1000)
        con = sqlite3.connect(db)
        con.execute("DELETE FROM speaker_segments")
        con.execute("INSERT INTO speaker_segments VALUES ('p', 1, 1000, 9000, ?, NULL, 1, "
                    "'face', 1.0)", (right,))
        con.execute("UPDATE face_detections SET asd = -2.0")   # no face looks like it talks
        con.commit()
        con.close()
        fr = compute_tracked_framing(db, "p", 0, 3000, source_size=(1920, 1080),
                                     canvas_size=(1080, 1920))
        assert fr is not None
        p = fr.pieces[0]
        t0, x0, _ = p.keyframes[0]
        assert t0 == 0 and x0 <= 1440 <= x0 + p.width        # on the right person from frame 0

    def test_no_tables_means_no_framing(self, tmp_path: Path) -> None:
        from clipcannon.editing.speaker_framing import compute_tracked_framing

        db = tmp_path / "empty.db"
        sqlite3.connect(db).close()
        assert compute_tracked_framing(db, "p", 0, 1000, source_size=(1920, 1080),
                                       canvas_size=(1080, 1920)) is None

    def test_schema_is_idempotent(self, tmp_path: Path) -> None:
        con = sqlite3.connect(tmp_path / "x.db")
        con.executescript(SCHEMA)
        con.executescript(SCHEMA)
        con.close()


# ------------------------------------------------------------------ ffmpeg chain
class TestTrackChain:
    def test_piecewise_expression(self) -> None:
        from clipcannon.rendering.ffmpeg_cmd import _piecewise_expr

        assert _piecewise_expr([(0.0, 5)]) == "5"
        e = _piecewise_expr([(0.0, 0), (1.0, 100)])
        assert e.startswith("if(lt(t\\,1.000)") and e.endswith("\\,100)")

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
    def test_tracked_framing_renders_with_ffmpeg(self, tmp_path: Path) -> None:
        from clipcannon.rendering.ffmpeg_cmd import _build_per_segment_canvas_cmd
        from clipcannon.rendering.profiles import get_profile

        src = tmp_path / "src.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=1920x1080:rate=30:duration=4", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=4", "-shortest", "-c:v", "libx264",
                        "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
        track = TrackedFraming(pieces=[
            TrackedPiece(start_ms=500, end_ms=2000, width=608, height=1080,
                         keyframes=[(500, 0, 0), (1500, 600, 0), (2000, 600, 0)]),
            TrackedPiece(start_ms=2000, end_ms=3500, width=404, height=720,
                         keyframes=[(2000, 1000, 200)]),
        ])
        seg = SegmentSpec(segment_id=1, source_start_ms=500, source_end_ms=3500,
                          output_start_ms=0, canvas=SegmentCanvasSpec(track=track))
        profile = get_profile("youtube_shorts")
        out = tmp_path / "out.mp4"
        cmd = _build_per_segment_canvas_cmd(src, out, [seg], profile, None, None,
                                            ["-c:v", "libx264", "-preset", "ultrafast",
                                             "-c:a", "aac"])
        run = subprocess.run(cmd, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr[-2000:]
        probe = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:"
             "format=duration", "-of", "json", str(out)],
            capture_output=True, text=True, check=True).stdout)
        v = next(s for s in probe["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (profile.width, profile.height)
        assert float(probe["format"]["duration"]) == pytest.approx(3.0, abs=0.15)
