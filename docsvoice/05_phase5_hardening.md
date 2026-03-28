# Phase 5: Production Hardening + Benchmarks

**Timeline**: Week 10
**Exit Criteria**: All benchmark targets met, Docker compose works, system runs unattended 24/7.
**Predecessor**: Phase 4 (dream state, memory, conversation intelligence all working)

---

## What Gets Built

Production polish: WebRTC transport, echo cancellation, noise suppression, concurrent conversations, health monitoring, Docker compose file, full benchmark suite, and text input fallback.

---

## 1. Echo Cancellation + Noise Suppression

### 1.1 Noise Suppression (`transport/noise_suppress.py`)

RNNoise removes background noise from mic input before ASR. CPU-only, <1ms per frame.

```python
class NoiseSuppressor:
    def __init__(self):
        import rnnoise
        self.denoiser = rnnoise.RNNoise()

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Denoise 16kHz audio. Process in 480-sample frames (30ms at 16kHz)."""
        FRAME_SIZE = 480
        output = np.zeros_like(audio, dtype=np.float32)
        for i in range(0, len(audio) - FRAME_SIZE, FRAME_SIZE):
            frame = audio[i:i+FRAME_SIZE].astype(np.float32)
            output[i:i+FRAME_SIZE] = self.denoiser.process_frame(frame)
        return output.astype(audio.dtype)
```

### 1.2 Echo Cancellation (`transport/echo_cancel.py`)

Prevents the agent from hearing its own TTS output through the mic. Uses SpeexDSP AEC.

```python
class EchoCanceller:
    def __init__(self, sample_rate=16000, frame_size=160):
        import speexdsp
        self.aec = speexdsp.EchoCanceller(frame_size, frame_size * 10, sample_rate)

    def process(self, mic_audio: np.ndarray, speaker_audio: np.ndarray) -> np.ndarray:
        """Remove speaker echo from mic signal."""
        return self.aec.process(mic_audio, speaker_audio)
```

---

## 2. Health Monitoring

### 2.1 Health Thread (`health/monitor.py`)

```python
class HealthMonitor:
    INTERVAL_S = 60
    HEARTBEAT_TIMEOUT_S = 90

    def __init__(self, ocr: OCRProvClient, captures_dir: Path, config):
        self.ocr = ocr
        self.captures_dir = captures_dir
        self.alerts = []

    def check_all(self):
        # OCR Provenance
        if not self.ocr.health():
            self.alerts.append("OCR Provenance container is down")

        # Companion heartbeat
        status_file = self.captures_dir / "companion_status.json"
        if status_file.exists():
            status = json.loads(status_file.read_text())
            last = datetime.fromisoformat(status["last_heartbeat"])
            if (datetime.now() - last).total_seconds() > self.HEARTBEAT_TIMEOUT_S:
                self.alerts.append(f"Companion hasn't reported in {int((datetime.now()-last).total_seconds())}s")
        else:
            self.alerts.append("Companion status file not found")

        # Disk usage
        usage = self._disk_usage_mb()
        limit = self.config.capture.max_disk_mb
        if usage > limit * 0.8:
            self.alerts.append(f"Capture storage {usage:.0f}MB / {limit}MB (>80%)")

        # GPU VRAM
        if torch.cuda.is_available():
            used = torch.cuda.memory_allocated() / 1e9
            total = torch.cuda.get_device_properties(0).total_mem / 1e9
            if used / total > 0.9:
                self.alerts.append(f"GPU VRAM {used:.1f}GB / {total:.1f}GB (>90%)")

        # Dream state
        last_dream = self._last_dream_date()
        if last_dream and (datetime.now() - last_dream).days > 2:
            self.alerts.append(f"Dream state hasn't run for {(datetime.now()-last_dream).days} days")

    def get_and_clear_alerts(self) -> list[str]:
        alerts = self.alerts.copy()
        self.alerts.clear()
        return alerts

    def run_loop(self):
        while True:
            self.check_all()
            time.sleep(self.INTERVAL_S)
```

### 2.2 Proactive Alert Surfacing

Injected at the start of conversation:

```python
# In ConversationManager._start_conversation():
alerts = self.health_monitor.get_and_clear_alerts()
if alerts:
    alert_text = "Before we start, I should let you know: " + "; ".join(alerts)
    # Synthesize and speak the alert
    await self._speak(alert_text)
```

---

## 3. Startup Self-Test

```python
class StartupSelfTest:
    def run(self) -> list[str]:
        """Run all checks. Returns list of failures. Empty = all passed."""
        failures = []

        # 1. OCR Provenance
        if not self.ocr.health():
            failures.append("OCR Provenance not reachable at localhost:3366")

        # 2. OCR Provenance MCP tools
        try:
            dbs = self.ocr.list_dbs()
        except Exception as e:
            failures.append(f"OCR Provenance MCP call failed: {e}")

        # 3. Qwen3-14B model files
        if not Path(self.config.llm.model_path).exists():
            failures.append(f"Qwen3-14B not found at {self.config.llm.model_path}")

        # 4. ClipCannon voice profile
        try:
            profile = get_voice_profile(self.config.tts.default_voice)
            if not profile:
                failures.append(f"Voice profile '{self.config.tts.default_voice}' not found")
        except Exception as e:
            failures.append(f"ClipCannon voice import failed: {e}")

        # 5. GPU
        if not torch.cuda.is_available():
            failures.append("CUDA not available")
        else:
            name = torch.cuda.get_device_name(0)
            if "5090" not in name:
                failures.append(f"Expected RTX 5090, got: {name}")

        # 6. Companion heartbeat file
        status_file = Path("/data/captures/companion_status.json")
        if not status_file.exists():
            failures.append("Companion status file not found — is companion running?")

        # 7. Audio device (audio comes from companion WAV files, no PulseAudio in Docker)
        # Audio comes from companion via WAV files, so this is optional

        # 8. Shared volume accessible
        if not Path("/data/captures").exists():
            failures.append("Shared volume /data/captures not mounted")

        return failures
```

On startup: run self-test. If any failures: print them all and exit with code 1. Do not start.

---

## 4. Text Input Fallback

For when you can't speak (meetings, library, late at night).

### 4.1 WebSocket Text Mode

Already supported — WebSocket accepts both binary (audio) and text (JSON) messages. Add a text message type:

```json
{"type": "text_input", "text": "What was I working on at 3pm yesterday?"}
```

The conversation manager routes this directly to the LLM, skipping ASR. Response can be text-only (no TTS) or spoken:

```json
{"type": "text_input", "text": "...", "speak_response": false}
```

### 4.2 CLI Text Mode

```bash
voiceagent ask "What was I working on at 3pm yesterday?"
# Returns text answer, no voice
```

---

## 5. Docker Compose

Final production `docker-compose.yml` in `docker/`:

```yaml
version: "3.8"

services:
  voiceagent:
    build:
      context: ..
      dockerfile: docker/voiceagent/Dockerfile
    container_name: voiceagent
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility
    ports:
      - "8765:8765"
      - "8080:8080"
    volumes:
      - voiceagent-data:/data/agent
      - type: bind
        source: C:\voiceagent_data
        target: /data/captures
      - type: bind
        source: \\\\wsl.localhost\\Ubuntu-24.04\\home\\cabdru\\.cache\\huggingface
        target: /root/.cache/huggingface
        read_only: true
      - type: bind
        source: \\\\wsl.localhost\\Ubuntu-24.04\\home\\cabdru\\.clipcannon
        target: /root/.clipcannon
        read_only: true
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s
    depends_on:
      ocr-provenance-mcp:
        condition: service_healthy
    networks:
      - voiceagent-net

  ocr-provenance-mcp:
    image: ghcr.io/nicholascross/ocr-provenance-mcp:latest
    container_name: ocr-provenance-mcp
    # ... existing OCR Provenance config unchanged ...
    networks:
      - voiceagent-net

networks:
  voiceagent-net:
    driver: bridge

volumes:
  voiceagent-data:
```

---

## 6. Benchmark Suite

### 6.1 Latency Benchmark (`eval/latency.py`)

```python
class LatencyBenchmark:
    def run(self, n_iterations=100):
        results = []
        for i in range(n_iterations):
            # Measure each stage
            t0 = time.perf_counter()
            asr_result = self.asr.transcribe(self.test_audio)
            t1 = time.perf_counter()
            llm_tokens = list(self.llm.generate(self.test_prompt))
            t2 = time.perf_counter()
            tts_audio = self.tts.synthesize(self.test_response)
            t3 = time.perf_counter()

            results.append({
                "asr_ms": (t1-t0)*1000,
                "llm_ttft_ms": (t2-t1)*1000,
                "tts_ttfb_ms": (t3-t2)*1000,
                "total_ms": (t3-t0)*1000,
            })

        # Report P50/P95/P99
        for metric in ["asr_ms", "llm_ttft_ms", "tts_ttfb_ms", "total_ms"]:
            values = sorted(r[metric] for r in results)
            print(f"{metric}: P50={values[50]:.0f} P95={values[95]:.0f} P99={values[99]:.0f}")
```

### 6.2 VAQI Benchmark (`eval/vaqi.py`)

Measures interruption handling, missed response windows, and latency. See PRD Section 17 for targets.

### 6.3 Memory Retrieval Accuracy (`eval/memory.py`)

```python
class MemoryBenchmark:
    def run(self):
        # Ingest known test data
        self._setup_test_data()

        # Query and check recall
        queries = [
            ("What app was I using at 3pm?", "Visual Studio Code"),
            ("Find the JWT authentication code", "JWT"),
            ("What did I copy to clipboard today?", "test clipboard content"),
        ]
        correct = 0
        for query, expected_substring in queries:
            results = self.ocr.search_cross_db(query, list(MANAGED_DATABASES.keys()))
            if any(expected_substring.lower() in r.get("text", "").lower()
                   for r in results.get("results", [])):
                correct += 1
        print(f"Memory recall: {correct}/{len(queries)}")
```

---

## 7. Verification Checklist

| # | Test | Source of Truth | Expected |
|---|------|----------------|----------|
| 1 | Noise suppression | Output audio RMS | Lower RMS than input on noisy test audio |
| 2 | Echo cancellation | Transcribe output | Agent's own speech NOT in transcript |
| 3 | Health monitor catches OCR down | Stop OCR container, wait 60s | Alert in health_monitor.alerts |
| 4 | Health monitor catches companion down | Kill companion, wait 90s | Alert surfaced |
| 5 | Startup self-test blocks on failure | Remove model path | Exit code 1, error printed |
| 6 | Text input via WebSocket | Send JSON text_input | Agent responds without ASR |
| 7 | CLI ask command | `voiceagent ask "hello"` | Text response printed |
| 8 | Docker compose up | `docker compose up -d` | Both containers healthy |
| 9 | Latency P95 | Benchmark 100 iterations | <500ms total |
| 10 | VAQI score | Run VAQI benchmark | >70 |
| 11 | Memory recall | Benchmark with known data | >90% accuracy |
| 12 | 24h unattended run | Run overnight with companion | Dream state completes, captures processed |

---

## 8. Final System Verification

After all phases complete, run the full verification matrix:

```bash
# 1. Start companion on Windows
voiceagent-capture.exe

# 2. Start Docker stack
docker compose up -d

# 3. Wait for startup self-test (check logs)
docker logs voiceagent | head -20

# 4. Verify companion heartbeat
cat C:\voiceagent_data\companion_status.json

# 5. Have a voice conversation
voiceagent talk --voice boris

# 6. Wait for dream state (or trigger manually)
# 7. Ask about yesterday's activity
# 8. Check all databases have data
# 9. Run benchmark suite
voiceagent bench --all --output docsvoice/benchmark_results/

# 10. Verify Docker health
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Every step must produce verifiable output. No step should be "it seems to work." Query the database. Check the file. Measure the latency. Read the logs.
