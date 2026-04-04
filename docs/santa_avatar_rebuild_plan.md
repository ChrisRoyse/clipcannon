# Santa Avatar Rebuild Plan

## Current State (2026-04-04)

### Assets Available
- **Voice clips**: ~80 WAV files from proj_2ea7221d (16-min interview, demucs-separated vocals)
- **Prosody data**: 197 prosody segments with F0/energy/rate features
- **Expression library**: 8 clips (2 laughs, 2 laugh contexts, 4 speech expressions)
- **Best reference**: santa_best_ref.wav (2.5s, F0~151Hz male)
- **Driver videos**: 6 files (idle Y4M 29MB, driver 5.9MB, reference JPG)
- **Source video**: 975.8s, 2560x1440, 60fps (docs/2026-04-03 04-23-11.mp4)
- **Voice profile**: Ready, SECS 0.95 threshold, 2048-dim ECAPA-TDNN embedding

### GPU Budget (34.2GB usable)
- Ollama 14B Q4_K_M: 4.1GB
- Whisper large-v3-turbo: 3-4GB
- TTS 0.6B: 2GB
- Total loaded during meeting: ~10GB
- **Free: ~24GB** (plenty for lip sync + rendering)

### Problems to Fix
1. Static video loop looks robotic (no lip movement when speaking)
2. Bot crashed on Ollama timeout (fixed — now catches errors)
3. OCR Provenance HTTP client needs MCP init handshake (fixed flow needed)
4. Expression library too thin (8 clips)
5. No real-time lip sync (MuseTalk blocked, LivePortrait not installed)
6. Prosody matching not wired into actual TTS calls in santa_meet_bot.py

## Rebuild Plan

### Phase A: Better Training Data (1-2 hours)

1. Extract more expression clips from the source video:
   - Find segments where Santa laughs loudly (prosody: high energy + high F0 variation)
   - Find segments where Santa sounds thoughtful (prosody: low energy, slow rate)
   - Find segments where Santa sounds surprised (prosody: rising F0, high peak)
   - Find segments where Santa sounds warm/comforting (prosody: medium energy, falling contour)
   - Target: 20+ expression clips across 5 emotional categories

2. Rebuild voice profile embedding from top prosody clips:
   - Filter prosody_segments by F0 < 165Hz (exclude interviewer)
   - Select top 30 clips by prosody_score
   - Recompute ECAPA-TDNN embedding from these clips

3. Create multiple reference clips for different prosody styles:
   - `ref_energetic.wav` — high energy, rising F0
   - `ref_calm.wav` — low energy, flat F0
   - `ref_question.wav` — rising contour
   - `ref_emphatic.wav` — strong emphasis markers
   - `ref_warm.wav` — medium energy, falling contour (Santa's natural delivery)

### Phase B: Better Driver Video (1-2 hours)

1. Extract a longer idle segment (15-30s) from the source video:
   - Find continuous segment where Santa is listening (mouth closed, natural motion)
   - Must include: natural breathing, slight head movement, eye blinks
   - Must NOT include: talking, dramatic gestures, looking away

2. Create multiple driver segments for different states:
   - `santa_idle_listen.y4m` — listening attentively (15-30s loop)
   - `santa_idle_think.y4m` — thinking/processing (looking slightly up/away)
   - `santa_nod.y4m` — gentle nodding (for agreement/acknowledgment)
   - State machine switches between these based on BehaviorEngine output

3. Y4M at higher quality:
   - 1280x720 (current resolution is fine)
   - 25fps for smooth motion
   - Ping-pong loop for seamless playback

### Phase C: LivePortrait for Real-Time Lip Sync (2-3 hours)

1. Install LivePortrait:
   ```bash
   pip install liveportrait
   ```
   Or clone from GitHub and install with TensorRT export

2. Create `src/phoenix/adapters/liveportrait_adapter.py`:
   - Wraps LivePortrait's reenactment API
   - Input: reference face image + audio-driven keypoints
   - Output: animated face frame at 30+ FPS
   - Uses TensorRT for Blackwell optimization

3. Audio-to-keypoint pipeline:
   - Extract mel spectrogram from TTS audio
   - Map to LivePortrait keypoints (mouth open/close, jaw, lips)
   - Feed alongside idle driver frame
   - Get back animated face that MOVES with speech

4. Integration with Chromium:
   - Instead of static Y4M, use named pipe (FIFO)
   - y4m_pipe_writer.py feeds frames from LivePortrait in real-time
   - When speaking: LivePortrait animated frames
   - When idle: driver video ping-pong loop

### Phase D: Full Prosody Pipeline (1 hour)

1. Wire ProsodyMatcher into santa_meet_bot.py:
   - Track room prosody from heard audio
   - Select TTS reference clip matching room energy
   - Pass prosody_style to FastTTSAdapter

2. Wire EmotionMirror into Y4M frame selection:
   - High room energy → more animated idle (santa_nod.y4m)
   - Low room energy → calm idle (santa_idle_think.y4m)
   - When addressed → attentive lean forward

3. Use CrossModalDetector for response style:
   - Humor detected → start with laugh clip
   - Tension detected → warm/comforting voice
   - Enthusiasm detected → energetic response

### Phase E: VRAM Management (30 min)

1. Model lifecycle in santa_meet_bot.py:
   - Whisper: load at startup, keep resident (3-4GB)
   - TTS: load at startup, keep resident (2GB)
   - Ollama: stays resident via server (4.1GB)
   - LivePortrait: load at startup (2GB)
   - Total: ~12GB resident, 22GB free

2. Garbage collection after every response:
   - `gc.collect()` after TTS synthesis
   - `torch.cuda.empty_cache()` after large inference
   - Cap numpy buffers (audio, frames) with explicit size limits

3. Monitor VRAM during meeting:
   - Log `torch.cuda.memory_allocated()` every 60s
   - Alert if allocated > 25GB

### Phase F: Comprehensive Testing (2 hours)

1. CuPy kernel stress test:
   - 1000 consecutive compositing operations
   - Measure VRAM before/after (should be identical)
   - Measure latency distribution (p50, p95, p99)

2. BehaviorEngine integration test:
   - Simulate 50-turn conversation
   - Verify emotion state converges (not oscillating)
   - Verify gesture selection is contextually appropriate
   - Verify prosody matching adapts to room energy changes

3. Full pipeline smoke test:
   - TTS synthesis of 10 Santa responses
   - Verify SECS > 0.95 on each
   - Measure latency breakdown (ASR, LLM, TTS, total)

4. Memory leak test:
   - Run 100 response cycles
   - Track VRAM at each cycle
   - Regression: VRAM must not grow by more than 100MB total
