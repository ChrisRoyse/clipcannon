"""build_labels(): the end-to-end clip labeling pipeline."""
import json
import logging
from dataclasses import asdict

import numpy as np

from .schema import (
    ALL_VISEMES,
    CLIP_DURATION_MS,
    CLIP_FRAMES,
    DB_PATH,
    OUTPUT_DIR,
    OUTPUT_LABELS,
    PROJECT_ID,
    TARGET_FPS,
    TeleologicalLabel,
)
from .sources import (
    build_frame_viseme_sequence,
    get_emotion_for_range,
    get_landmarks_for_frame,
    get_prosody_for_range,
    is_in_long_silence,
    load_analysis_data,
    load_cmu_dict,
    load_precomputed_landmarks,
    word_to_visemes,
)

log = logging.getLogger("label")


def build_labels():
    """Main pipeline: create labeled clips from ClipCannon data."""
    log.info("=" * 70)
    log.info("  TELEOLOGICAL CONSTELLATION LABELING PIPELINE")
    log.info("=" * 70)

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load ClipCannon analysis data
    data = load_analysis_data(DB_PATH, PROJECT_ID)

    # Load precomputed face landmarks (the single source of truth)
    landmarks = load_precomputed_landmarks()
    max_landmarks_ms = int(landmarks["timestamp_ms"][-1])
    log.info("Landmarks cover up to %dms", max_landmarks_ms)

    cmu = load_cmu_dict()
    words = data["words"]

    # Pre-compute visemes for all words
    log.info("Computing viseme sequences for all words...")
    all_visemes = []
    for w in words:
        visemes = word_to_visemes(w["word"], cmu, w["start_ms"], w["end_ms"])
        all_visemes.extend(visemes)
    log.info("Total viseme segments: %d", len(all_visemes))

    # Viseme distribution stats
    viseme_counts = {}
    for v, _, _ in all_visemes:
        viseme_counts[v] = viseme_counts.get(v, 0) + 1
    log.info("Viseme distribution:")
    for v in sorted(viseme_counts.keys()):
        log.info("  %-5s: %d", v, viseme_counts[v])

    log.info("Building clip labels (one per word)...")
    labels: list[TeleologicalLabel] = []
    skipped_negative = 0
    skipped_beyond_landmarks = 0
    skipped_silence = 0
    skipped_no_detection = 0

    for i, word in enumerate(words):
        word_center = (word["start_ms"] + word["end_ms"]) // 2
        clip_start = word_center - CLIP_DURATION_MS // 2
        clip_end = clip_start + CLIP_DURATION_MS

        # Filter: clip must start after time 0
        if clip_start < 0:
            skipped_negative += 1
            continue

        # Filter: clip must be within landmark coverage
        if clip_end > max_landmarks_ms:
            skipped_beyond_landmarks += 1
            continue

        # Filter: skip clips inside long silences (likely not Santa speaking)
        if is_in_long_silence(word_center, data["silence_gaps"]):
            skipped_silence += 1
            continue

        # Collect per-frame landmarks for this clip
        face_bboxes = []
        mouth_bboxes = []
        mouth_centers = []
        detected_flags = []
        scores = []

        for frame_idx in range(CLIP_FRAMES):
            frame_ms = clip_start + frame_idx * (CLIP_DURATION_MS / CLIP_FRAMES)
            lm = get_landmarks_for_frame(landmarks, int(frame_ms))
            face_bboxes.append(lm["bbox"])
            mouth_bboxes.append(lm["mouth_bbox"])
            mouth_cx = (lm["mouth_bbox"][0] + lm["mouth_bbox"][2]) / 2
            mouth_cy = (lm["mouth_bbox"][1] + lm["mouth_bbox"][3]) / 2
            mouth_centers.append([mouth_cx, mouth_cy])
            detected_flags.append(lm["detected"])
            scores.append(lm["score"])

        # Filter: require at least 30/49 frames to have real detections (not backfilled)
        n_detected = sum(detected_flags)
        if n_detected < 30:
            skipped_no_detection += 1
            continue

        # Collect words in clip
        words_in_clip = [
            (w["word"], w["start_ms"], w["end_ms"])
            for w in words
            if clip_start <= w["start_ms"] < clip_end
            or clip_start < w["end_ms"] <= clip_end
        ]

        # Collect visemes in clip
        visemes_in_clip = [
            (v, vs, ve)
            for v, vs, ve in all_visemes
            if clip_start <= vs < clip_end or clip_start < ve <= clip_end
        ]

        viseme_seq = build_frame_viseme_sequence(visemes_in_clip, clip_start, CLIP_FRAMES)

        # Prosody + emotion context
        prosody = get_prosody_for_range(clip_start, clip_end, data["prosody"])
        arousal, valence, energy = get_emotion_for_range(clip_start, clip_end, data["emotion"])

        # Classify clip
        has_speech = not is_in_long_silence(word_center, data["silence_gaps"])
        if not has_speech:
            category = "breathing"
        elif prosody and prosody.get("has_emphasis"):
            category = "emotional"
        else:
            category = "speaking"

        label = TeleologicalLabel(
            clip_id=f"{len(labels):05d}",
            start_ms=clip_start,
            end_ms=clip_end,
            center_word=word["word"],
            center_word_ms=word_center,
            words=words_in_clip,
            visemes=visemes_in_clip,
            viseme_sequence=viseme_seq,
            face_bbox_per_frame=face_bboxes,
            mouth_bbox_per_frame=mouth_bboxes,
            mouth_center_per_frame=mouth_centers,
            frames_detected=n_detected,
            mean_face_score=float(np.mean(scores)),
            prosody_f0_mean=float(prosody["f0_mean"]) if prosody else 0.0,
            prosody_f0_std=float(prosody["f0_std"]) if prosody else 0.0,
            prosody_energy_mean=float(prosody["energy_mean"]) if prosody else 0.0,
            prosody_energy_peak=float(prosody["energy_peak"]) if prosody else 0.0,
            prosody_speaking_rate=float(prosody["speaking_rate_wpm"]) if prosody else 0.0,
            prosody_energy_level=prosody["energy_level"] if prosody else "medium",
            prosody_contour_type=prosody["pitch_contour_type"] if prosody else "flat",
            prosody_has_emphasis=bool(prosody["has_emphasis"]) if prosody else False,
            prosody_has_breath=bool(prosody["has_breath"]) if prosody else False,
            emotion_arousal=arousal,
            emotion_valence=valence,
            emotion_energy=energy,
            has_speech=has_speech,
            clip_category=category,
        )
        labels.append(label)

        if (i + 1) % 500 == 0:
            log.info("Processed %d/%d words (kept %d)", i + 1, len(words), len(labels))

    log.info("")
    log.info("=" * 60)
    log.info("  FILTERING SUMMARY")
    log.info("=" * 60)
    log.info("Total words:              %d", len(words))
    log.info("Skipped — negative start: %d", skipped_negative)
    log.info("Skipped — beyond landmarks: %d", skipped_beyond_landmarks)
    log.info("Skipped — long silence:   %d", skipped_silence)
    log.info("Skipped — <30/49 detected: %d", skipped_no_detection)
    log.info("Kept clips:               %d", len(labels))

    # Category breakdown
    by_category = {}
    for l in labels:
        by_category[l.clip_category] = by_category.get(l.clip_category, 0) + 1
    log.info("Categories: %s", by_category)

    # Viseme diversity
    diversity = [len(set(l.viseme_sequence)) for l in labels]
    log.info("Viseme diversity per clip: mean=%.1f max=%d",
             float(np.mean(diversity)), int(np.max(diversity)))

    # Quality stats
    scores = [l.mean_face_score for l in labels]
    log.info("Mean face score across clips: %.2f-%.2f (avg %.2f)",
             float(np.min(scores)), float(np.max(scores)), float(np.mean(scores)))

    # Save to JSON
    labels_dict = {
        "project_id": PROJECT_ID,
        "total_clips": len(labels),
        "clip_frames": CLIP_FRAMES,
        "clip_duration_ms": CLIP_DURATION_MS,
        "target_fps": TARGET_FPS,
        "viseme_categories": ALL_VISEMES,
        "clips": [asdict(l) for l in labels],
    }

    OUTPUT_LABELS.write_text(json.dumps(labels_dict, indent=2), encoding="utf-8")
    log.info("Saved labels: %s (%.1f MB)",
             OUTPUT_LABELS, OUTPUT_LABELS.stat().st_size / 1e6)

    return labels_dict
