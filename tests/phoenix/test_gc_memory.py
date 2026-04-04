"""GC and memory leak tests for the meeting pipeline.

Tests that repeated cycles of:
  - Audio buffer creation and processing
  - EmotionFusion embedding processing
  - SpeakerTracker embedding processing
  - BehaviorEngine processing
  - Transcript segment accumulation
  - CuPy GPU compositor operations
do NOT leak memory (RSS or VRAM).

Targets:
  - RSS growth < 50MB over 100 cycles
  - VRAM growth < 100MB over 100 cycles (if GPU available)
  - No uncollectable garbage objects
"""
from __future__ import annotations

import gc
import os
import time

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_rss_mb() -> float:
    """Get current process RSS in MB (Linux only)."""
    try:
        with open(f"/proc/{os.getpid()}/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError):
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def get_vram_mb() -> float | None:
    """Get current CuPy VRAM allocated in MB, or None if unavailable."""
    try:
        import cupy as cp
        pool = cp.get_default_memory_pool()
        return pool.used_bytes() / (1024 * 1024)
    except Exception:
        return None


def force_gc():
    """Aggressive garbage collection."""
    gc.collect()
    gc.collect()
    gc.collect()


# ---------------------------------------------------------------------------
# Test: Audio buffer cycle (simulates santa_meet_bot.py main loop)
# ---------------------------------------------------------------------------

class TestAudioBufferMemory:
    """Test that audio buffer accumulation and processing doesn't leak."""

    def test_100_audio_cycles_no_rss_leak(self):
        """Simulate 100 cycles of audio capture → transcribe-sized buffer → clear."""
        force_gc()
        rss_start = get_rss_mb()
        rss_samples = []

        for i in range(100):
            # Simulate 5s of 16kHz audio accumulating in a bytearray
            buf = bytearray()
            for _ in range(50):  # 50 chunks of 100ms
                chunk = np.random.randint(-32768, 32767, 1600, dtype=np.int16).tobytes()
                buf.extend(chunk)

            # Convert to float32 (like transcribe path)
            audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
            assert audio.shape[0] == 80000  # 5s at 16kHz

            # Simulate processing
            energy = float(np.sqrt(np.mean(audio ** 2)))
            assert energy > 0

            # Simulate PCM conversion for playback
            pcm = (audio * 32767).astype(np.int16).tobytes()
            assert len(pcm) == 160000

            # Clean up (matches santa_meet_bot.py pattern)
            del buf, audio, pcm

            if i % 10 == 0:
                force_gc()
                rss_samples.append(get_rss_mb())

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"\nAudio buffer test: RSS start={rss_start:.1f}MB, end={rss_end:.1f}MB, growth={growth:.1f}MB")
        print(f"  RSS samples every 10 cycles: {[f'{x:.1f}' for x in rss_samples]}")
        assert growth < 50, f"RSS grew {growth:.1f}MB > 50MB limit over 100 audio cycles"


# ---------------------------------------------------------------------------
# Test: EmotionFusion repeated processing
# ---------------------------------------------------------------------------

class TestEmotionFusionMemory:
    """Test EmotionFusion doesn't leak across repeated fuse/update calls."""

    def test_100_fusion_cycles_no_leak(self):
        """Run 100 fuse + update cycles and check memory growth."""
        from phoenix.expression.emotion_fusion import EmotionFusion, ProsodyFeatures

        force_gc()
        rss_start = get_rss_mb()

        fusion = EmotionFusion()

        for _ in range(100):
            emotion_emb = np.random.randn(1024).astype(np.float32)
            semantic_emb = np.random.randn(768).astype(np.float32)
            f0_mean = 150.0 + np.random.randn() * 20
            f0_std = 30.0 + abs(np.random.randn() * 5)
            f0_min = f0_mean - 40
            f0_max = f0_mean + 40
            prosody = ProsodyFeatures(
                f0_mean=f0_mean,
                f0_std=f0_std,
                f0_min=f0_min,
                f0_max=f0_max,
                f0_range=f0_max - f0_min,
                energy_mean=0.5 + np.random.randn() * 0.1,
                energy_peak=0.8,
                energy_std=0.1,
                speaking_rate_wpm=150.0 + np.random.randn() * 20,
                pitch_contour_type="varied",
                has_emphasis=bool(np.random.randint(2)),
                has_breath=bool(np.random.randint(2)),
            )
            state = fusion.fuse(emotion_emb, prosody, semantic_emb)
            fusion.update(state)
            del emotion_emb, semantic_emb, prosody, state

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"\nEmotionFusion test: RSS growth={growth:.1f}MB")
        assert growth < 20, f"EmotionFusion leaked {growth:.1f}MB over 100 cycles"


# ---------------------------------------------------------------------------
# Test: SpeakerTracker repeated tracking
# ---------------------------------------------------------------------------

class TestSpeakerTrackerMemory:
    """Test SpeakerTracker doesn't leak with repeated track() calls."""

    def test_500_track_cycles_bounded_speakers(self):
        """Track 500 embeddings (rotating 5 speakers) — memory must stay bounded."""
        from phoenix.expression.speaker_tracker import SpeakerTracker

        force_gc()
        rss_start = get_rss_mb()

        # Use a lower threshold since random embeddings with small noise
        # still need high cosine similarity to re-identify
        tracker = SpeakerTracker(similarity_threshold=0.85)

        # Pre-generate 5 well-separated speaker embeddings using orthogonal-ish vectors
        rng = np.random.RandomState(42)
        speakers = []
        for _ in range(5):
            v = rng.randn(512).astype(np.float32)
            v /= np.linalg.norm(v)
            speakers.append(v)

        for i in range(500):
            # Rotate through speakers with very small noise to stay above threshold
            base = speakers[i % 5].copy()
            noise = rng.randn(512).astype(np.float32) * 0.01
            noisy = base + noise
            noisy /= np.linalg.norm(noisy)
            info = tracker.track(noisy, timestamp_ms=i * 1000)
            assert info is not None
            del noisy, noise

        # Should have identified approximately 5 speakers (allow some noise-induced extras)
        assert tracker.speaker_count <= 10, f"Too many speakers: {tracker.speaker_count}"
        print(f"\nSpeakerTracker: identified {tracker.speaker_count} speakers from 5 sources over 500 calls")

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"SpeakerTracker test: RSS growth={growth:.1f}MB")
        assert growth < 20, f"SpeakerTracker leaked {growth:.1f}MB over 500 track() calls"


# ---------------------------------------------------------------------------
# Test: BehaviorEngine full cycle
# ---------------------------------------------------------------------------

class TestBehaviorEngineMemory:
    """Test BehaviorEngine doesn't leak across repeated process cycles."""

    def test_50_behavior_cycles_no_leak(self):
        """Simulate 50-turn conversation through BehaviorEngine."""
        from phoenix.behavior.engine import BehaviorEngine

        force_gc()
        rss_start = get_rss_mb()

        engine = BehaviorEngine()

        from phoenix.expression.emotion_fusion import ProsodyFeatures

        for i in range(50):
            # Listening phase
            emotion_emb = np.random.randn(1024).astype(np.float32)
            speaker_emb = np.random.randn(512).astype(np.float32)
            speaker_emb /= np.linalg.norm(speaker_emb)
            semantic_emb = np.random.randn(768).astype(np.float32)
            f0_mean = 140.0 + np.random.randn() * 30
            prosody = ProsodyFeatures(
                f0_mean=f0_mean, f0_std=25.0, f0_min=f0_mean - 30,
                f0_max=f0_mean + 30, f0_range=60.0,
                energy_mean=0.4 + np.random.rand() * 0.4,
                energy_peak=0.8, energy_std=0.1,
                speaking_rate_wpm=150.0, pitch_contour_type="varied",
                has_emphasis=False, has_breath=False,
            )

            output = engine.process_listening(
                emotion_embedding=emotion_emb,
                speaker_embedding=speaker_emb,
                semantic_embedding=semantic_emb,
                prosody=prosody,
                timestamp_ms=i * 5000,
            )
            assert output is not None

            # Speaking phase
            speaking_output = engine.process_speaking(
                response_text=f"Test response number {i} with some varied content.",
                emotion_embedding=emotion_emb,
                prosody=prosody,
                semantic_embedding=semantic_emb,
            )
            assert speaking_output is not None

            del emotion_emb, speaker_emb, semantic_emb, prosody, output, speaking_output

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"\nBehaviorEngine test: RSS growth={growth:.1f}MB over 50 turns")
        assert growth < 30, f"BehaviorEngine leaked {growth:.1f}MB over 50 conversation turns"


# ---------------------------------------------------------------------------
# Test: Transcript segment accumulation and trimming
# ---------------------------------------------------------------------------

class TestTranscriptMemory:
    """Test transcript buffer trimming keeps memory bounded."""

    def test_1000_segments_stay_bounded(self):
        """Add 1000 transcript segments, verify memory stays bounded at cap."""
        force_gc()
        rss_start = get_rss_mb()

        MAX_SEGMENTS = 200
        segments: list[dict] = []

        for i in range(1000):
            seg = {
                "speaker": f"Speaker_{i % 5}",
                "text": f"This is test segment number {i} with some realistic length text content " * 3,
                "timestamp": f"{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}",
            }
            segments.append(seg)

            # Trim (matches santa_meet_bot.py pattern)
            if len(segments) > MAX_SEGMENTS:
                del segments[:len(segments) - MAX_SEGMENTS]

        assert len(segments) == MAX_SEGMENTS
        assert segments[0]["text"].startswith("This is test segment number 800")

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"\nTranscript test: RSS growth={growth:.1f}MB, segments={len(segments)}")
        assert growth < 10, f"Transcript leaked {growth:.1f}MB over 1000 segment adds"


# ---------------------------------------------------------------------------
# Test: CuPy GPU memory leak test
# ---------------------------------------------------------------------------

class TestGPUMemoryLeak:
    """Test CuPy operations don't leak VRAM."""

    @pytest.fixture(autouse=True)
    def _check_cupy(self):
        """Skip if CuPy/CUDA not available."""
        try:
            import cupy as cp
            cp.cuda.Device(0).compute_capability
        except Exception:
            pytest.skip("CuPy/CUDA not available")

    def test_100_gpu_cycles_no_vram_leak(self):
        """Run 100 cycles of GPU compositor ops, measure VRAM delta."""
        import cupy as cp

        pool = cp.get_default_memory_pool()
        pool.free_all_blocks()
        force_gc()

        vram_start = pool.used_bytes()
        vram_samples = []

        for i in range(100):
            # Simulate face compositing pipeline
            frame = cp.random.random((720, 1280, 4), dtype=cp.float32)
            face = cp.random.random((256, 256, 4), dtype=cp.float32)
            overlay = cp.random.random((720, 1280, 4), dtype=cp.float32)

            # Alpha blend
            alpha = overlay[:, :, 3:4]
            blended = frame * (1 - alpha) + overlay * alpha

            # Resize face
            small = face[:128, :128, :]  # simple crop as resize proxy

            # Film grain
            noise = cp.random.normal(0, 0.02, frame.shape[:2]).astype(cp.float32)
            frame[:, :, :3] += noise[:, :, cp.newaxis]
            frame = cp.clip(frame, 0, 1)

            # Cleanup
            del frame, face, overlay, alpha, blended, small, noise

            if i % 10 == 0:
                pool.free_all_blocks()
                force_gc()
                vram_samples.append(pool.used_bytes() / (1024 * 1024))

        pool.free_all_blocks()
        force_gc()
        vram_end = pool.used_bytes()
        growth_mb = (vram_end - vram_start) / (1024 * 1024)

        print(f"\nGPU memory test: VRAM growth={growth_mb:.2f}MB")
        print(f"  VRAM samples every 10 cycles (MB): {[f'{x:.1f}' for x in vram_samples]}")
        assert growth_mb < 100, f"GPU VRAM leaked {growth_mb:.1f}MB over 100 cycles"

    def test_compositor_bridge_no_leak(self):
        """Test compositor_bridge numpy<->CuPy transfer doesn't leak."""
        import cupy as cp

        try:
            from phoenix.render.compositor_bridge import (
                gpu_alpha_blend,
                gpu_brightness_jitter,
                gpu_composite_face,
                gpu_film_grain,
            )
        except ImportError:
            pytest.skip("phoenix.render.compositor_bridge not available")

        pool = cp.get_default_memory_pool()
        pool.free_all_blocks()
        force_gc()
        vram_start = pool.used_bytes()

        for i in range(50):
            frame = np.random.randint(0, 256, (720, 1280, 4), dtype=np.uint8)
            face = np.random.randint(0, 256, (256, 256, 4), dtype=np.uint8)
            overlay = np.random.randint(0, 256, (720, 1280, 4), dtype=np.uint8)

            # Test each bridge function
            result = gpu_alpha_blend(frame, overlay, 0.5)
            assert result.shape == frame.shape

            result = gpu_film_grain(frame, 0.02)
            assert result.shape == frame.shape

            result = gpu_brightness_jitter(frame, 5.0)
            assert result.shape == frame.shape

            try:
                result = gpu_composite_face(frame, face, 100, 100, 256, 256)
                assert result.shape == frame.shape
            except Exception:
                pass  # May fail if face region out of bounds

            del frame, face, overlay, result

            if i % 10 == 0:
                pool.free_all_blocks()
                force_gc()

        pool.free_all_blocks()
        force_gc()
        vram_end = pool.used_bytes()
        growth_mb = (vram_end - vram_start) / (1024 * 1024)

        print(f"\nBridge memory test: VRAM growth={growth_mb:.2f}MB over 50 cycles")
        assert growth_mb < 50, f"Bridge leaked {growth_mb:.1f}MB VRAM over 50 cycles"


# ---------------------------------------------------------------------------
# Test: Combined pipeline memory stress
# ---------------------------------------------------------------------------

class TestCombinedPipelineMemory:
    """Test the full pipeline cycle doesn't leak memory."""

    def test_full_pipeline_50_cycles(self):
        """Simulate 50 full response cycles (audio -> behavior -> TTS sim -> cleanup)."""
        from phoenix.behavior.engine import BehaviorEngine
        from phoenix.expression.emotion_fusion import EmotionFusion, ProsodyFeatures
        from phoenix.expression.speaker_tracker import SpeakerTracker

        force_gc()
        rss_start = get_rss_mb()

        engine = BehaviorEngine()
        fusion = EmotionFusion()
        tracker = SpeakerTracker()
        segments: list[dict] = []

        for i in range(50):
            # 1. Audio capture simulation
            audio_buf = np.random.randn(80000).astype(np.float32)
            energy = float(np.sqrt(np.mean(audio_buf ** 2)))

            # 2. Embeddings
            emotion_emb = np.random.randn(1024).astype(np.float32)
            speaker_emb = np.random.randn(512).astype(np.float32)
            speaker_emb /= np.linalg.norm(speaker_emb)
            semantic_emb = np.random.randn(768).astype(np.float32)
            f0_mean = 150.0 + np.random.randn() * 20
            prosody = ProsodyFeatures(
                f0_mean=f0_mean, f0_std=30.0, f0_min=f0_mean - 30,
                f0_max=f0_mean + 30, f0_range=60.0,
                energy_mean=min(max(energy, 0.0), 1.0),
                energy_peak=0.8, energy_std=0.1,
                speaking_rate_wpm=150.0, pitch_contour_type="varied",
                has_emphasis=False, has_breath=False,
            )

            # 3. Emotion fusion
            state = fusion.fuse(emotion_emb, prosody, semantic_emb)
            fusion.update(state)

            # 4. Speaker tracking
            speaker = tracker.track(speaker_emb, timestamp_ms=i * 5000)

            # 5. Behavior engine
            output = engine.process_listening(
                emotion_embedding=emotion_emb,
                speaker_embedding=speaker_emb,
                semantic_embedding=semantic_emb,
                prosody=prosody,
                timestamp_ms=i * 5000,
            )

            # 6. TTS simulation (PCM buffer)
            tts_audio = np.random.randn(240000).astype(np.float32)  # 10s at 24kHz
            pcm = (tts_audio * 32767).astype(np.int16).tobytes()

            # 7. Transcript
            segments.append({"speaker": speaker.speaker_id, "text": f"Turn {i}", "ts": f"{i}"})
            if len(segments) > 200:
                del segments[:len(segments) - 200]

            # 8. Cleanup (matches real pipeline)
            del audio_buf, emotion_emb, speaker_emb, semantic_emb
            del prosody, state, speaker, output, tts_audio, pcm
            gc.collect()

        force_gc()
        rss_end = get_rss_mb()
        growth = rss_end - rss_start

        print(f"\nFull pipeline test: RSS growth={growth:.1f}MB over 50 cycles")
        print(f"  Tracked speakers: {tracker.speaker_count}")
        assert growth < 50, f"Full pipeline leaked {growth:.1f}MB over 50 response cycles"


# ---------------------------------------------------------------------------
# Test: gc.collect() effectiveness
# ---------------------------------------------------------------------------

class TestGarbageCollection:
    """Test that gc.collect() properly frees circular references."""

    def test_no_uncollectable_garbage(self):
        """Verify no uncollectable garbage after typical Phoenix operations."""
        # Clear any pre-existing garbage first
        gc.collect()
        gc.garbage.clear()

        # Baseline: count uncollectable objects before our operations
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        baseline = len(gc.garbage)
        gc.garbage.clear()

        # Create typical Phoenix objects (embeddings, states, etc.)
        from phoenix.expression.emotion_fusion import EmotionFusion, ProsodyFeatures
        fusion = EmotionFusion()
        for _ in range(50):
            emb = np.random.randn(1024).astype(np.float32)
            prosody = ProsodyFeatures(
                f0_mean=150.0, f0_std=30.0, f0_min=120.0, f0_max=180.0,
                f0_range=60.0, energy_mean=0.5, energy_peak=0.8,
                energy_std=0.1, speaking_rate_wpm=150.0,
                pitch_contour_type="varied", has_emphasis=False, has_breath=False,
            )
            state = fusion.fuse(emb, prosody)
            fusion.update(state)
            del emb, prosody, state
        del fusion

        gc.collect()
        new_garbage = len(gc.garbage) - baseline
        gc.set_debug(0)
        gc.garbage.clear()

        print(f"\nGC test: new uncollectable objects = {new_garbage} (baseline was {baseline})")
        assert new_garbage == 0, f"Phoenix operations created {new_garbage} uncollectable objects"

    def test_large_numpy_arrays_freed(self):
        """Verify large numpy arrays are freed by gc.collect()."""
        force_gc()
        rss_before = get_rss_mb()

        # Allocate ~500MB of numpy arrays
        arrays = [np.random.randn(1000, 1000).astype(np.float64) for _ in range(60)]
        rss_peak = get_rss_mb()
        assert rss_peak - rss_before > 100, "Arrays didn't allocate enough memory for test"

        del arrays
        force_gc()
        rss_after = get_rss_mb()

        freed = rss_peak - rss_after
        print(f"\nLarge array GC: peak={rss_peak:.0f}MB, after gc={rss_after:.0f}MB, freed={freed:.0f}MB")
        assert freed > 200, f"gc.collect() only freed {freed:.0f}MB of ~500MB allocated"
