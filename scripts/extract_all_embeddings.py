#!/usr/bin/env python3
"""Extract ALL 7 embedding modalities from Santa's ClipCannon database into a single NPZ.

Modalities:
  1. vis_emb (N, 1152) + vis_ts  -- SigLIP frame embeddings from vec_frames
  2. sem_emb (N, 768)  + sem_ts  -- Nomic semantic embeddings from vec_semantic
  3. emo_emb (N, 1024) + emo_ts  -- Wav2Vec2 emotion embeddings from vec_emotion
  4. spk_emb (N, 512)  + spk_ts  -- WavLM speaker embeddings from vec_speakers
  5. pro_data (N, 12)  + pro_ts  -- Prosody scalar features from prosody_segments
  6. sent_emb (N, 384) + sent_ts -- MiniLM sentence embeddings (computed from transcript)
  7. voice_emb (N, 192) + voice_ts -- ECAPA speaker identity (computed from audio)
  8. flame_exp (N, 100) + flame_ts -- FLAME expression params from flame_params.npz

Interviewer filtering: cluster WavLM embeddings into 2 speakers via k-means,
identify Santa as the dominant speaker, build time masks, and filter all modalities.
"""

import os
import sys
import struct
import sqlite3
import warnings
import shutil

# --- Offline mode BEFORE any ML imports ---
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

import numpy as np

# ============================================================
# Configuration
# ============================================================
PROJECT_ID = "proj_2ea7221d"
DB_PATH = "/home/cabdru/.clipcannon/projects/proj_2ea7221d/analysis.db"
VOCALS_PATH = "/home/cabdru/.clipcannon/projects/proj_2ea7221d/stems/vocals.wav"
FLAME_PATH = "/home/cabdru/.clipcannon/models/santa/flame_params.npz"
OUTPUT_PATH = "/home/cabdru/.clipcannon/models/santa/embeddings/all_embeddings.npz"
BACKUP_PATH = OUTPUT_PATH + ".bak_with_interviewer"
MARGIN_MS = 500  # Interviewer filtering margin

# ============================================================
# sqlite-vec binary extraction helpers
# ============================================================

def decode_validity(blob, chunk_size=1024):
    """Decode sqlite-vec validity bitmap (LSB-first bit ordering)."""
    raw = np.frombuffer(blob, dtype=np.uint8)
    bits = np.zeros(chunk_size, dtype=np.uint8)
    for i in range(chunk_size):
        bits[i] = (raw[i // 8] >> (i % 8)) & 1
    return bits


def extract_vec_table(conn, table_name, dim, ts_chunk_index=None):
    """Extract vectors and timestamps from a sqlite-vec virtual table's backing stores.

    Args:
        conn: sqlite3 connection
        table_name: e.g. 'vec_emotion'
        dim: embedding dimension (e.g. 1024)
        ts_chunk_index: which metadatachunks table holds int64 timestamps
                        (e.g. 1 for metadatachunks01)

    Returns:
        (vectors, timestamps) as numpy arrays, or (vectors, None) if no ts_chunk_index
    """
    # Get all chunks
    chunks = conn.execute(
        f"SELECT chunk_id, size, validity FROM {table_name}_chunks ORDER BY chunk_id"
    ).fetchall()

    all_vectors = []
    all_timestamps = []

    for chunk_id, chunk_size, validity_blob in chunks:
        valid_mask = decode_validity(validity_blob, chunk_size)
        valid_idx = np.where(valid_mask == 1)[0]

        # Read vector blob
        vec_blob = conn.execute(
            f"SELECT vectors FROM {table_name}_vector_chunks00 WHERE rowid=?",
            (chunk_id,),
        ).fetchone()[0]
        vecs = np.frombuffer(vec_blob, dtype=np.float32).reshape(chunk_size, dim)
        all_vectors.append(vecs[valid_idx])

        # Read timestamps if requested
        if ts_chunk_index is not None:
            ts_blob = conn.execute(
                f"SELECT data FROM {table_name}_metadatachunks{ts_chunk_index:02d} WHERE rowid=?",
                (chunk_id,),
            ).fetchone()[0]
            ts = np.frombuffer(ts_blob, dtype=np.int64)
            all_timestamps.append(ts[valid_idx])

    vectors = np.concatenate(all_vectors, axis=0)
    timestamps = np.concatenate(all_timestamps, axis=0) if all_timestamps else None
    return vectors, timestamps


# ============================================================
# Step 1: Extract DB embeddings
# ============================================================
def extract_db_embeddings():
    """Extract all vector embeddings from the database."""
    conn = sqlite3.connect(DB_PATH)

    print("[1/8] Extracting vis_emb (SigLIP 1152d) from vec_frames...")
    # vec_frames: metadatachunks01 = timestamp_ms (int64)
    vis_emb, vis_ts = extract_vec_table(conn, "vec_frames", dim=1152, ts_chunk_index=1)
    print(f"  vis_emb: {vis_emb.shape}, vis_ts: {vis_ts.shape}")

    print("[2/8] Extracting sem_emb (Nomic 768d) from vec_semantic...")
    # vec_semantic: metadatachunks01 = start_ms (int64)
    sem_emb, sem_ts = extract_vec_table(conn, "vec_semantic", dim=768, ts_chunk_index=1)
    print(f"  sem_emb: {sem_emb.shape}, sem_ts: {sem_ts.shape}")

    print("[3/8] Extracting emo_emb (Wav2Vec2 1024d) from vec_emotion...")
    # vec_emotion: metadatachunks01 = start_ms, metadatachunks02 = end_ms
    emo_emb, emo_ts = extract_vec_table(conn, "vec_emotion", dim=1024, ts_chunk_index=1)
    print(f"  emo_emb: {emo_emb.shape}, emo_ts: {emo_ts.shape}")

    print("[4/8] Extracting spk_emb (WavLM 512d) from vec_speakers...")
    # vec_speakers: metadatachunks02 = start_ms (int64)
    spk_emb, spk_ts = extract_vec_table(conn, "vec_speakers", dim=512, ts_chunk_index=2)
    print(f"  spk_emb: {spk_emb.shape}, spk_ts: {spk_ts.shape}")

    print("[5/8] Extracting pro_data (12 scalars) from prosody_segments...")
    rows = conn.execute(
        """SELECT start_ms, end_ms,
                  f0_mean, f0_std, f0_min, f0_max, f0_range,
                  energy_mean, energy_peak, energy_std,
                  speaking_rate_wpm, prosody_score,
                  has_emphasis, has_breath
           FROM prosody_segments
           WHERE project_id = ?
           ORDER BY start_ms""",
        (PROJECT_ID,),
    ).fetchall()
    pro_starts = np.array([r[0] for r in rows], dtype=np.int64)
    pro_ends = np.array([r[1] for r in rows], dtype=np.int64)
    pro_ts = (pro_starts + pro_ends) // 2  # midpoint
    pro_data = np.array(
        [[r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13]] for r in rows],
        dtype=np.float32,
    )
    print(f"  pro_data: {pro_data.shape}, pro_ts: {pro_ts.shape}")

    # Also get transcript texts + timestamps for sentence embedding computation
    print("  Loading transcript texts for sentence embedding computation...")
    t_rows = conn.execute(
        """SELECT start_ms, end_ms, text
           FROM transcript_segments
           WHERE project_id = ?
           ORDER BY start_ms""",
        (PROJECT_ID,),
    ).fetchall()
    sent_starts = np.array([r[0] for r in t_rows], dtype=np.int64)
    sent_ends = np.array([r[1] for r in t_rows], dtype=np.int64)
    sent_ts = (sent_starts + sent_ends) // 2
    sent_texts = [r[2] for r in t_rows]
    print(f"  transcript segments: {len(sent_texts)}")

    # Prosody segments for voice embedding computation (need start/end for audio slicing)
    pro_segments = [(r[0], r[1]) for r in rows]  # (start_ms, end_ms)

    conn.close()

    return {
        "vis_emb": vis_emb, "vis_ts": vis_ts,
        "sem_emb": sem_emb, "sem_ts": sem_ts,
        "emo_emb": emo_emb, "emo_ts": emo_ts,
        "spk_emb": spk_emb, "spk_ts": spk_ts,
        "pro_data": pro_data, "pro_ts": pro_ts, "pro_starts": pro_starts, "pro_ends": pro_ends,
        "sent_ts": sent_ts, "sent_texts": sent_texts,
        "pro_segments": pro_segments,
    }


# ============================================================
# Step 2: Compute sentence embeddings (MiniLM)
# ============================================================
def compute_sentence_embeddings(texts):
    """Compute sentence embeddings using all-MiniLM-L6-v2."""
    print("[6/8] Computing sent_emb (MiniLM 384d) from transcript texts...")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2",
        cache_folder=os.path.expanduser("~/.cache/huggingface/hub"),
    )
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True)
    embeddings = np.array(embeddings, dtype=np.float32)
    print(f"  sent_emb: {embeddings.shape}")
    return embeddings


# ============================================================
# Step 3: Compute ECAPA voice embeddings per prosody segment
# ============================================================
def compute_voice_embeddings(pro_segments):
    """Compute ECAPA-TDNN speaker embeddings per prosody segment from vocals.wav."""
    print("[7/8] Computing voice_emb (ECAPA 192d) from audio per prosody segment...")

    import torch
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    from huggingface_hub import snapshot_download

    # Load ECAPA model from the HF cache (downloaded on first use; no
    # machine-specific snapshot path)
    cache_dir = snapshot_download(repo_id="speechbrain/spkrec-ecapa-voxceleb")
    classifier = EncoderClassifier.from_hparams(
        source=cache_dir,
        run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"},
    )

    # Load audio (vocals stem)
    # Use soundfile for reliability
    import soundfile as sf
    audio_data, sr = sf.read(VOCALS_PATH, dtype="float32")
    if audio_data.ndim == 2:
        audio_data = audio_data.mean(axis=1)  # mono
    audio_tensor = torch.tensor(audio_data, dtype=torch.float32)

    # Target 16kHz for ECAPA
    if sr != 16000:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)
        audio_tensor = resampler(audio_tensor)
        sr = 16000

    embeddings = []
    for i, (start_ms, end_ms) in enumerate(pro_segments):
        start_sample = int(start_ms * sr / 1000)
        end_sample = int(end_ms * sr / 1000)
        segment = audio_tensor[start_sample:end_sample]

        if len(segment) < sr * 0.1:  # less than 100ms
            embeddings.append(np.zeros(192, dtype=np.float32))
            continue

        with torch.no_grad():
            emb = classifier.encode_batch(segment.unsqueeze(0).to(classifier.device))
            embeddings.append(emb.squeeze().cpu().numpy().astype(np.float32))

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(pro_segments)} segments")

    voice_emb = np.stack(embeddings, axis=0)
    print(f"  voice_emb: {voice_emb.shape}")
    return voice_emb


# ============================================================
# Step 4: Load FLAME expression params
# ============================================================
def load_flame_params():
    """Load FLAME expression parameters."""
    print("[8/8] Loading flame_exp (100d) from flame_params.npz...")
    flame = np.load(FLAME_PATH)
    flame_exp = flame["expression"].astype(np.float32)
    flame_ts = flame["timestamps"].astype(np.float32)
    print(f"  flame_exp: {flame_exp.shape}, flame_ts: {flame_ts.shape}")
    return flame_exp, flame_ts


# ============================================================
# Step 5: Interviewer filtering via speaker clustering
# ============================================================
def build_santa_mask(spk_emb, spk_ts):
    """Cluster WavLM speaker embeddings into 2 speakers via k-means.
    Identify Santa as the dominant speaker (more segments = more speaking time).
    Return a list of (start_ms, end_ms) intervals for Santa's speech.
    """
    print("\n=== Interviewer Filtering ===")
    from sklearn.cluster import KMeans

    # K-means clustering into 2 speakers
    kmeans = KMeans(n_clusters=2, random_state=42, n_init=10)
    labels = kmeans.fit_predict(spk_emb)

    # Count segments per cluster
    unique, counts = np.unique(labels, return_counts=True)
    print(f"  Cluster 0: {counts[0]} segments, Cluster 1: {counts[1]} segments")

    # Santa is the dominant speaker (more segments)
    santa_label = unique[np.argmax(counts)]
    interviewer_label = unique[np.argmin(counts)]
    print(f"  Santa = cluster {santa_label} ({counts[santa_label]} segments)")
    print(f"  Interviewer = cluster {interviewer_label} ({counts[interviewer_label]} segments)")

    # Build Santa speaking intervals from speaker embeddings
    # Each speaker embedding has a start_ms. Estimate end by next segment start or +3s
    santa_mask = labels == santa_label
    santa_starts = spk_ts[santa_mask]

    # Sort and build intervals
    sort_idx = np.argsort(santa_starts)
    santa_starts_sorted = santa_starts[sort_idx]

    # For end times, use gap to next segment or default duration
    # We have ~3s segments from the speaker diarization
    intervals = []
    for i, start in enumerate(santa_starts_sorted):
        if i + 1 < len(santa_starts_sorted):
            # Use gap to next Santa segment, but cap at 5s
            end = min(start + 5000, santa_starts_sorted[i + 1])
        else:
            end = start + 5000
        intervals.append((int(start - MARGIN_MS), int(end + MARGIN_MS)))

    # Merge overlapping intervals
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    total_santa_ms = sum(e - s for s, e in merged)
    print(f"  Santa intervals: {len(merged)}, total: {total_santa_ms/1000:.1f}s")

    return merged


def filter_by_santa_intervals(data, ts, intervals):
    """Filter embeddings/data to only keep timestamps within Santa's intervals."""
    mask = np.zeros(len(ts), dtype=bool)
    for start, end in intervals:
        mask |= (ts >= start) & (ts <= end)
    return data[mask], ts[mask]


def filter_flame_by_santa_intervals(flame_exp, flame_ts_float, intervals):
    """Filter FLAME params (float timestamps in seconds) by Santa intervals."""
    flame_ts_ms = (flame_ts_float * 1000).astype(np.int64)
    mask = np.zeros(len(flame_ts_ms), dtype=bool)
    for start, end in intervals:
        mask |= (flame_ts_ms >= start) & (flame_ts_ms <= end)
    return flame_exp[mask], flame_ts_float[mask]


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("Extracting ALL 7 embedding modalities for Santa")
    print("=" * 60)

    # Step 1: Extract from DB
    data = extract_db_embeddings()

    # Step 2: Compute sentence embeddings
    sent_emb = compute_sentence_embeddings(data["sent_texts"])

    # Step 3: Compute voice embeddings
    voice_emb = compute_voice_embeddings(data["pro_segments"])
    voice_ts = data["pro_ts"].copy()  # Same timestamps as prosody

    # Step 4: Load FLAME
    flame_exp, flame_ts = load_flame_params()

    # --- Save unfiltered backup if it does not exist ---
    if not os.path.exists(BACKUP_PATH):
        print(f"\nSaving unfiltered backup to {BACKUP_PATH}...")
        np.savez_compressed(
            BACKUP_PATH,
            vis_emb=data["vis_emb"], vis_ts=data["vis_ts"],
            sem_emb=data["sem_emb"], sem_ts=data["sem_ts"],
            emo_emb=data["emo_emb"], emo_ts=data["emo_ts"],
            spk_emb=data["spk_emb"], spk_ts=data["spk_ts"],
            pro_data=data["pro_data"], pro_ts=data["pro_ts"],
            sent_emb=sent_emb, sent_ts=data["sent_ts"],
            voice_emb=voice_emb, voice_ts=voice_ts,
            flame_exp=flame_exp, flame_ts=flame_ts,
        )
    else:
        print(f"\nBackup already exists at {BACKUP_PATH}, not overwriting.")

    # Step 5: Interviewer filtering
    santa_intervals = build_santa_mask(data["spk_emb"], data["spk_ts"])

    # Filter each modality
    print("\nFiltering modalities to Santa-only...")

    vis_emb_f, vis_ts_f = filter_by_santa_intervals(data["vis_emb"], data["vis_ts"], santa_intervals)
    print(f"  vis_emb: {data['vis_emb'].shape[0]} -> {vis_emb_f.shape[0]}")

    sem_emb_f, sem_ts_f = filter_by_santa_intervals(data["sem_emb"], data["sem_ts"], santa_intervals)
    print(f"  sem_emb: {data['sem_emb'].shape[0]} -> {sem_emb_f.shape[0]}")

    emo_emb_f, emo_ts_f = filter_by_santa_intervals(data["emo_emb"], data["emo_ts"], santa_intervals)
    print(f"  emo_emb: {data['emo_emb'].shape[0]} -> {emo_emb_f.shape[0]}")

    spk_emb_f, spk_ts_f = filter_by_santa_intervals(data["spk_emb"], data["spk_ts"], santa_intervals)
    print(f"  spk_emb: {data['spk_emb'].shape[0]} -> {spk_emb_f.shape[0]}")

    pro_data_f, pro_ts_f = filter_by_santa_intervals(data["pro_data"], data["pro_ts"], santa_intervals)
    print(f"  pro_data: {data['pro_data'].shape[0]} -> {pro_data_f.shape[0]}")

    sent_emb_f, sent_ts_f = filter_by_santa_intervals(sent_emb, data["sent_ts"], santa_intervals)
    print(f"  sent_emb: {sent_emb.shape[0]} -> {sent_emb_f.shape[0]}")

    voice_emb_f, voice_ts_f = filter_by_santa_intervals(voice_emb, voice_ts, santa_intervals)
    print(f"  voice_emb: {voice_emb.shape[0]} -> {voice_emb_f.shape[0]}")

    flame_exp_f, flame_ts_f = filter_flame_by_santa_intervals(flame_exp, flame_ts, santa_intervals)
    print(f"  flame_exp: {flame_exp.shape[0]} -> {flame_exp_f.shape[0]}")

    # Step 6: Save final NPZ
    print(f"\nSaving final NPZ to {OUTPUT_PATH}...")
    np.savez_compressed(
        OUTPUT_PATH,
        vis_emb=vis_emb_f, vis_ts=vis_ts_f,
        sem_emb=sem_emb_f, sem_ts=sem_ts_f,
        emo_emb=emo_emb_f, emo_ts=emo_ts_f,
        spk_emb=spk_emb_f, spk_ts=spk_ts_f,
        pro_data=pro_data_f, pro_ts=pro_ts_f,
        sent_emb=sent_emb_f, sent_ts=sent_ts_f,
        voice_emb=voice_emb_f, voice_ts=voice_ts_f,
        flame_exp=flame_exp_f, flame_ts=flame_ts_f,
    )

    # Verification
    print("\n" + "=" * 60)
    print("VERIFICATION - Final NPZ contents:")
    print("=" * 60)
    npz = np.load(OUTPUT_PATH)
    for k in sorted(npz.files):
        arr = npz[k]
        print(f"  {k:15s}: shape={str(arr.shape):20s}  dtype={arr.dtype}")
    npz.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
