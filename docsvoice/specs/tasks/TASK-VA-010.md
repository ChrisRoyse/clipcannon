```xml
<task_spec id="TASK-VA-010" version="2.0">
<metadata>
  <title>ClipCannon Adapter -- Voice Profile Loading and synthesize() Method</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>10</sequence>
  <implements>
    <item ref="PHASE1-TTS-ADAPTER">ClipCannonAdapter wrapping voice synthesis</item>
    <item ref="PHASE1-VERIFY-3">ClipCannon TTS produces audio (verification #3)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Wraps ClipCannon's voice synthesis system for use by the voice agent. Loads a voice
profile by name from ClipCannon's voice_profiles.db, initializes the VoiceSynthesizer,
and provides an async synthesize(text) method that returns 24kHz float32 audio as a
numpy array. The StreamingTTS (TASK-VA-012) calls this for each sentence chunk.

CRITICAL API CORRECTIONS (verified from actual source code):
- get_voice_profile(db_path, name) -- db_path is FIRST arg (str|Path), name is SECOND
- speak() has NO 'enhance' parameter -- enhancement is a SEPARATE post-process call
  via clipcannon.voice.enhance.enhance_speech(input_path, output_path)
  For real-time: simply do NOT call enhance_speech() afterward
- speak() returns SpeakResult dataclass with audio_path (Path to WAV file on disk),
  NOT a numpy array. The adapter must READ the WAV file to get a numpy array.
- reference_embedding in profile DB is stored as BLOB -- deserialize with
  np.frombuffer(blob, dtype=np.float32) to get 2048-dim float32 vector
- Reference audio clips live at ~/.clipcannon/voice_data/{voice_name}/wavs/
- Profile dict keys: profile_id, name, model_path, training_hours, training_projects
  (JSON str), sample_rate (24000), reference_embedding (bytes/BLOB),
  verification_threshold (float, default 0.80), training_status, created_at, updated_at
- For real-time: max_attempts=1 (don't retry), speed=1.0
- output_path: use tempfile.mktemp(suffix=".wav"), delete WAV after reading

IMPORTANT: src/voiceagent/ does NOT exist yet. This is 100% greenfield code.
All Python imports need PYTHONPATH=src from the repo root.
</context>

<input_context_files>
  <file purpose="adapter_spec">docsvoice/01_phase1_core_pipeline.md#section-4.1</file>
  <file purpose="config">src/voiceagent/config.py (created by TASK-VA-002)</file>
  <file purpose="errors">src/voiceagent/errors.py (created by TASK-VA-001)</file>
  <file purpose="clipcannon_profiles">src/clipcannon/voice/profiles.py (EXISTING -- the real ClipCannon API)</file>
  <file purpose="clipcannon_inference">src/clipcannon/voice/inference.py (EXISTING -- the real ClipCannon API)</file>
  <file purpose="clipcannon_enhance">src/clipcannon/voice/enhance.py (EXISTING -- NOT used for real-time)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-002 complete (TTSConfig available)</check>
  <check>ClipCannon voice module available at src/clipcannon/voice/</check>
  <check>Voice profile "boris" exists in ~/.clipcannon/voice_profiles.db</check>
  <check>Reference audio files exist at ~/.clipcannon/voice_data/boris/wavs/</check>
  <check>soundfile package installed (pip install soundfile)</check>
</prerequisites>

<real_clipcannon_api>
  PROFILES (src/clipcannon/voice/profiles.py):
    get_voice_profile(db_path: str | Path, name: str) -> dict[str, object] | None
    list_voice_profiles(db_path: str | Path) -> list[dict[str, object]]
    create_voice_profile(db_path: str | Path, name: str, model_path: str, sample_rate: int = 24000) -> str

  INFERENCE (src/clipcannon/voice/inference.py):
    class VoiceSynthesizer:
        # Lazy loads Qwen3-TTS model on first speak()
        def speak(
            self,
            text: str,
            output_path: Path,
            reference_audio: Path | None = None,
            reference_text: str | None = None,
            reference_embedding: np.ndarray | None = None,
            verification_threshold: float = 0.80,
            max_attempts: int = 5,
            temperature: float = 0.8,
            max_new_tokens: int = 2048,
            speed: float = 1.0,
        ) -> SpeakResult: ...
        def release(self) -> None: ...  # frees GPU VRAM

    @dataclass
    class SpeakResult:
        audio_path: Path
        duration_ms: int
        sample_rate: int          # 24000
        verification: VerificationResult | None
        attempts: int
        parameters_used: dict

  VERIFY (src/clipcannon/voice/verify.py):
    build_reference_embedding(audio_paths: list[Path]) -> np.ndarray  # 2048-dim L2-normalized
    class VoiceVerifier:
        def __init__(self, reference_embedding: np.ndarray, threshold: float = 0.80): ...

  ENHANCE (src/clipcannon/voice/enhance.py):
    enhance_speech(input_path: Path, output_path: Path) -> Path
    # NOT USED for real-time -- adds ~500ms latency per chunk

  THERE IS NO 'enhance' PARAMETER ON speak(). Enhancement is a separate post-processing step.
</real_clipcannon_api>

<scope>
  <in_scope>
    - ClipCannonAdapter class in src/voiceagent/adapters/clipcannon.py
    - __init__(voice_name, db_path) loads voice profile from DB
    - synthesize(text) -> np.ndarray (24kHz float32)
    - Calls VoiceSynthesizer.speak() with max_attempts=1, speed=1.0 (real-time settings)
    - Reads WAV file from speak() result, returns as numpy array, cleans up temp file
    - Resolves reference audio from ~/.clipcannon/voice_data/{voice_name}/wavs/
    - Deserializes reference_embedding from profile BLOB
    - release() to free GPU memory
    - Integration tests using REAL "boris" voice profile (NO MOCKS of ClipCannon)
  </in_scope>
  <out_of_scope>
    - Voice profile creation/training
    - Resemble Enhance post-processing (NOT used for real-time)
    - Streaming within a single synthesis call (speak() is per-sentence)
    - Mocking ClipCannon -- tests use real voice profiles and real synthesis
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/adapters/clipcannon.py">
      import numpy as np

      class ClipCannonAdapter:
          DEFAULT_DB: str = "~/.clipcannon/voice_profiles.db"
          VOICE_DATA_DIR: str = "~/.clipcannon/voice_data"

          def __init__(self, voice_name: str = "boris", db_path: str | None = None) -> None: ...
          async def synthesize(self, text: str) -> np.ndarray: ...
          def release(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - get_voice_profile(db_path, name) -- db_path is FIRST arg, name is SECOND
    - speak() called WITHOUT any 'enhance' parameter (it does not exist)
    - speak() returns SpeakResult with audio_path (Path to WAV on disk)
    - After speak(), read WAV via soundfile.read(audio_path, dtype="float32") to get numpy array
    - Delete temp WAV file after reading (os.unlink)
    - reference_audio: first .wav file found in ~/.clipcannon/voice_data/{voice_name}/wavs/
    - reference_embedding: np.frombuffer(profile["reference_embedding"], dtype=np.float32) if not None
    - verification_threshold: float(profile.get("verification_threshold", 0.80))
    - max_attempts=1 for real-time (don't retry on verification failure)
    - speed=1.0 for real-time
    - output_path: tempfile.mktemp(suffix=".wav")
    - synthesize() is async: wraps sync speak() with asyncio.to_thread
    - Raise TTSError (from voiceagent.errors) if voice profile not found
    - Raise TTSError if synthesis fails (with descriptive message: what/why/how-to-fix)
    - Raise TTSError if no reference audio found
    - release() calls synth.release() to free GPU VRAM
    - Output sample rate: 24000 Hz
    - NO MOCKS in tests -- use real "boris" profile
  </constraints>

  <verification>
    - ClipCannonAdapter("boris") instantiates and loads profile successfully
    - synthesize("Hello world") returns numpy array with dtype=float32
    - Returned audio has sample_rate=24000
    - Duration is reasonable: 0.5-5 seconds for "Hello world" (12000-120000 samples)
    - TTSError raised for nonexistent voice profile
    - release() does not raise
    - Temp WAV file is cleaned up after synthesize()
    - pytest tests/voiceagent/test_clipcannon_adapter.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/adapters/clipcannon.py:
  """ClipCannon voice synthesis adapter for the voice agent.

  Wraps ClipCannon's VoiceSynthesizer for real-time TTS. Loads a voice profile,
  resolves reference audio, and provides async synthesize(text) -> np.ndarray.
  """
  from __future__ import annotations
  import asyncio
  import logging
  import os
  import tempfile
  from pathlib import Path

  import numpy as np
  import soundfile as sf

  from voiceagent.errors import TTSError

  logger = logging.getLogger(__name__)

  class ClipCannonAdapter:
      DEFAULT_DB = "~/.clipcannon/voice_profiles.db"
      VOICE_DATA_DIR = "~/.clipcannon/voice_data"

      def __init__(self, voice_name: str = "boris", db_path: str | None = None) -> None:
          self._voice_name = voice_name
          db = str(Path(db_path or self.DEFAULT_DB).expanduser())

          # Load voice profile
          from clipcannon.voice.profiles import get_voice_profile
          self._profile = get_voice_profile(db, voice_name)
          if self._profile is None:
              raise TTSError(
                  f"Voice profile '{voice_name}' not found in {db}. "
                  f"Create it first with: clipcannon voice profile create {voice_name}"
              )
          logger.info("Loaded voice profile '%s' (id=%s)", voice_name, self._profile.get("profile_id"))

          # Resolve reference audio
          voice_wavs_dir = Path(self.VOICE_DATA_DIR).expanduser() / voice_name / "wavs"
          self._reference_audio = self._find_reference_audio(voice_wavs_dir)

          # Deserialize reference embedding from profile BLOB (if present)
          self._reference_embedding = None
          raw_embedding = self._profile.get("reference_embedding")
          if raw_embedding is not None and len(raw_embedding) > 0:
              self._reference_embedding = np.frombuffer(raw_embedding, dtype=np.float32)
              logger.info(
                  "Loaded reference embedding: shape=%s, norm=%.4f",
                  self._reference_embedding.shape,
                  np.linalg.norm(self._reference_embedding),
              )

          # Verification threshold
          self._verification_threshold = float(self._profile.get("verification_threshold", 0.80))

          # Initialize synthesizer (lazy-loads model on first speak())
          from clipcannon.voice.inference import VoiceSynthesizer
          self._synth = VoiceSynthesizer()
          logger.info("ClipCannonAdapter initialized for voice '%s'", voice_name)

      def _find_reference_audio(self, wavs_dir: Path) -> Path:
          """Find first .wav reference clip in voice data directory."""
          if not wavs_dir.is_dir():
              raise TTSError(
                  f"Voice data directory not found: {wavs_dir}. "
                  f"Expected reference WAV files at {wavs_dir}/*.wav"
              )
          wav_files = sorted(wavs_dir.glob("*.wav"))
          if not wav_files:
              raise TTSError(
                  f"No .wav reference files found in {wavs_dir}. "
                  f"Add reference recordings to {wavs_dir}/ first."
              )
          logger.info("Using reference audio: %s", wav_files[0])
          return wav_files[0]

      async def synthesize(self, text: str) -> np.ndarray:
          """Synthesize text to 24kHz float32 audio array.

          Calls ClipCannon speak() in a thread (it's synchronous), reads the WAV
          result, returns as numpy array, and cleans up the temp file.

          Args:
              text: Text to synthesize.

          Returns:
              numpy array of float32 audio samples at 24kHz.

          Raises:
              TTSError: If text is empty or synthesis fails.
          """
          if not text or not text.strip():
              raise TTSError("Cannot synthesize empty text.")

          tmp_path = Path(tempfile.mktemp(suffix=".wav"))
          try:
              # speak() is synchronous -- run in thread to avoid blocking event loop
              result = await asyncio.to_thread(
                  self._synth.speak,
                  text=text,
                  output_path=tmp_path,
                  reference_audio=self._reference_audio,
                  reference_embedding=self._reference_embedding,
                  verification_threshold=self._verification_threshold,
                  max_attempts=1,    # single attempt for real-time latency
                  speed=1.0,         # normal speed for real-time
              )

              # Read WAV file into numpy array
              if not result.audio_path.exists():
                  raise TTSError(
                      f"speak() returned audio_path={result.audio_path} but file does not exist. "
                      f"Check ClipCannon logs for synthesis errors."
                  )

              audio, sr = sf.read(str(result.audio_path), dtype="float32")
              logger.info(
                  "Synthesized '%s': duration=%dms, samples=%d, sr=%d, attempts=%d",
                  text[:50], result.duration_ms, len(audio), sr, result.attempts,
              )
              return audio

          except TTSError:
              raise
          except Exception as exc:
              raise TTSError(
                  f"Synthesis failed for text '{text[:80]}': {exc}. "
                  f"Check that Qwen3-TTS model is loaded and GPU has sufficient VRAM."
              ) from exc
          finally:
              # Clean up temp WAV file
              if tmp_path.exists():
                  try:
                      os.unlink(tmp_path)
                  except OSError:
                      logger.warning("Failed to clean up temp file: %s", tmp_path)

      def release(self) -> None:
          """Free GPU VRAM by releasing the synthesizer."""
          if hasattr(self, "_synth") and self._synth is not None:
              self._synth.release()
              logger.info("Released VoiceSynthesizer GPU resources")

tests/voiceagent/test_clipcannon_adapter.py:
  """Integration tests for ClipCannonAdapter using REAL 'boris' voice profile.

  NO MOCKS of ClipCannon. These tests require:
  - Voice profile 'boris' in ~/.clipcannon/voice_profiles.db
  - Reference audio at ~/.clipcannon/voice_data/boris/wavs/
  - Qwen3-TTS model (loaded lazily by VoiceSynthesizer)
  - GPU available (RTX 5090)
  """
  import asyncio
  import numpy as np
  import pytest
  from pathlib import Path

  from voiceagent.adapters.clipcannon import ClipCannonAdapter
  from voiceagent.errors import TTSError

  @pytest.fixture(scope="module")
  def adapter():
      """Create adapter once for all tests (model loading is expensive)."""
      a = ClipCannonAdapter(voice_name="boris")
      yield a
      a.release()

  def test_adapter_loads_profile(adapter):
      """Verify adapter loaded the boris profile successfully."""
      assert adapter._profile is not None
      assert adapter._profile["name"] == "boris"
      assert adapter._reference_audio.exists()
      assert adapter._reference_audio.suffix == ".wav"

  def test_adapter_profile_has_expected_keys(adapter):
      """Verify profile dict has the expected structure."""
      expected_keys = {"profile_id", "name", "model_path", "sample_rate"}
      assert expected_keys.issubset(set(adapter._profile.keys()))
      assert adapter._profile["sample_rate"] == 24000

  def test_adapter_raises_on_missing_profile():
      """TTSError for nonexistent voice profile."""
      with pytest.raises(TTSError, match="not found"):
          ClipCannonAdapter(voice_name="nonexistent_voice_xyz_12345")

  def test_synthesize_returns_float32_array(adapter):
      """Synthesize 'Hello world' and verify output format."""
      audio = asyncio.get_event_loop().run_until_complete(
          adapter.synthesize("Hello world")
      )
      assert isinstance(audio, np.ndarray)
      assert audio.dtype == np.float32
      assert audio.ndim == 1  # mono audio
      # Duration: 0.5-5 seconds for "Hello world" at 24kHz
      assert len(audio) > 12000, f"Audio too short: {len(audio)} samples ({len(audio)/24000:.2f}s)"
      assert len(audio) < 120000, f"Audio too long: {len(audio)} samples ({len(audio)/24000:.2f}s)"
      print(f"Synthesized {len(audio)} samples ({len(audio)/24000:.2f}s)")

  def test_synthesize_empty_text_raises(adapter):
      """TTSError for empty text."""
      with pytest.raises(TTSError, match="empty"):
          asyncio.get_event_loop().run_until_complete(
              adapter.synthesize("")
          )

  def test_synthesize_whitespace_only_raises(adapter):
      """TTSError for whitespace-only text."""
      with pytest.raises(TTSError, match="empty"):
          asyncio.get_event_loop().run_until_complete(
              adapter.synthesize("   ")
          )

  def test_temp_wav_cleaned_up(adapter):
      """Verify temp WAV is deleted after synthesize()."""
      import glob
      import tempfile
      before = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
      asyncio.get_event_loop().run_until_complete(
          adapter.synthesize("Testing cleanup")
      )
      after = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
      new_files = after - before
      assert len(new_files) == 0, f"Temp WAV not cleaned up: {new_files}"

  def test_release_does_not_raise():
      """release() on a fresh adapter does not raise."""
      a = ClipCannonAdapter(voice_name="boris")
      a.release()  # should not raise

  def test_synthesize_longer_text(adapter):
      """Synthesize a longer sentence and verify output."""
      audio = asyncio.get_event_loop().run_until_complete(
          adapter.synthesize("The quick brown fox jumps over the lazy dog near the riverbank.")
      )
      assert isinstance(audio, np.ndarray)
      assert audio.dtype == np.float32
      assert len(audio) > 24000  # at least 1 second for this text
      print(f"Long text: {len(audio)} samples ({len(audio)/24000:.2f}s)")
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/adapters/clipcannon.py">ClipCannonAdapter class</file>
  <file path="src/voiceagent/adapters/__init__.py">Empty init for adapters package</file>
  <file path="tests/voiceagent/test_clipcannon_adapter.py">Integration tests with real boris profile</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>get_voice_profile called with (db_path, name) -- db_path FIRST</criterion>
  <criterion>speak() called WITHOUT 'enhance' parameter (it does not exist)</criterion>
  <criterion>speak() result read via soundfile.read(audio_path) to get numpy array</criterion>
  <criterion>Temp WAV file cleaned up after reading</criterion>
  <criterion>max_attempts=1, speed=1.0 for real-time</criterion>
  <criterion>reference_embedding deserialized with np.frombuffer(blob, dtype=np.float32)</criterion>
  <criterion>Reference audio resolved from ~/.clipcannon/voice_data/{name}/wavs/</criterion>
  <criterion>synthesize returns float32 numpy array at 24kHz</criterion>
  <criterion>TTSError raised for missing profile, empty text, synthesis failure</criterion>
  <criterion>All tests use REAL boris profile -- NO MOCKS of ClipCannon</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>
    1. The numpy array returned by synthesize() -- its dtype, shape, and sample count
    2. The temp WAV file on disk (should NOT exist after synthesize completes)
    3. The voice profile loaded from ~/.clipcannon/voice_profiles.db
  </source_of_truth>
  <execute_and_inspect>
    1. Instantiate ClipCannonAdapter("boris")
    2. Print adapter._profile to verify profile loaded
    3. Print adapter._reference_audio to verify path exists
    4. Call await synthesize("Hello world")
    5. SEPARATELY check: audio.dtype, audio.shape, len(audio)/24000 for duration
    6. Check temp directory for leftover WAV files
  </execute_and_inspect>
  <edge_case_audit>
    EDGE CASE 1: Empty text
      BEFORE: adapter ready, text=""
      AFTER: TTSError raised with message containing "empty"
      Print: str(exc) to verify descriptive message

    EDGE CASE 2: Very long text (>1000 chars)
      BEFORE: adapter ready, text="The quick brown fox..." * 50
      AFTER: speak() returns SpeakResult, audio is a long numpy array
      Print: len(audio), duration_seconds = len(audio)/24000

    EDGE CASE 3: Nonexistent voice profile
      BEFORE: ClipCannonAdapter("nonexistent_xyz")
      AFTER: TTSError raised with message containing "not found"
      Print: str(exc) includes profile name and db path

    EDGE CASE 4: None voice_name
      BEFORE: ClipCannonAdapter(voice_name=None)  -- should fail or use default
      AFTER: get_voice_profile(db_path, None) returns None -> TTSError
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_clipcannon_adapter.py -v
    # All tests pass

    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio
    import numpy as np
    from voiceagent.adapters.clipcannon import ClipCannonAdapter

    adapter = ClipCannonAdapter('boris')
    print(f'Profile: {adapter._profile[\"name\"]}')
    print(f'Reference audio: {adapter._reference_audio}')

    audio = asyncio.run(adapter.synthesize('Hello world'))
    print(f'Output dtype: {audio.dtype}')
    print(f'Output shape: {audio.shape}')
    print(f'Duration: {len(audio)/24000:.2f} seconds')
    print(f'Sample range: [{audio.min():.4f}, {audio.max():.4f}]')
    assert audio.dtype == np.float32
    assert len(audio) > 12000
    adapter.release()
    print('ALL CHECKS PASSED')
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  TEST 1 -- Basic synthesis:
    Input:  text="Hello world", voice="boris"
    Output: numpy array, dtype=float32, length > 12000 samples (>0.5s at 24kHz)
    Duration: 0.5-5.0 seconds

  TEST 2 -- Longer text:
    Input:  text="The quick brown fox jumps over the lazy dog near the riverbank."
    Output: numpy array, dtype=float32, length > 24000 samples (>1.0s at 24kHz)

  TEST 3 -- Empty text:
    Input:  text=""
    Output: TTSError raised with "empty" in message

  TEST 4 -- Nonexistent profile:
    Input:  voice_name="nonexistent_voice_xyz_12345"
    Output: TTSError raised with "not found" in message

  TEST 5 -- Temp file cleanup:
    Input:  text="Testing cleanup"
    Output: After synthesize() returns, no new .wav files in /tmp/
</synthetic_test_data>

<manual_verification>
  STEP 1: Verify ClipCannon API signatures match
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import inspect
    from clipcannon.voice.profiles import get_voice_profile
    sig = inspect.signature(get_voice_profile)
    print(f'get_voice_profile signature: {sig}')
    # Verify: (db_path: str | Path, name: str)

    from clipcannon.voice.inference import VoiceSynthesizer
    sig = inspect.signature(VoiceSynthesizer.speak)
    print(f'speak() signature: {sig}')
    # Verify: NO 'enhance' parameter

    from clipcannon.voice.inference import SpeakResult
    print(f'SpeakResult fields: {[f.name for f in __import__(\"dataclasses\").fields(SpeakResult)]}')
    # Verify: audio_path, duration_ms, sample_rate, verification, attempts, parameters_used
    "

  STEP 2: Verify boris profile exists
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from clipcannon.voice.profiles import get_voice_profile
    p = get_voice_profile(str(__import__('pathlib').Path('~/.clipcannon/voice_profiles.db').expanduser()), 'boris')
    print(f'Profile keys: {list(p.keys())}')
    print(f'Name: {p[\"name\"]}')
    print(f'Sample rate: {p[\"sample_rate\"]}')
    print(f'Embedding size: {len(p[\"reference_embedding\"]) if p.get(\"reference_embedding\") else \"None\"} bytes')
    "

  STEP 3: Verify reference audio exists
    ls -la ~/.clipcannon/voice_data/boris/wavs/

  STEP 4: Run integration tests
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_clipcannon_adapter.py -v

  STEP 5: Manual synthesis test
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio, numpy as np
    from voiceagent.adapters.clipcannon import ClipCannonAdapter
    a = ClipCannonAdapter('boris')
    audio = asyncio.run(a.synthesize('Hello world'))
    print(f'dtype={audio.dtype}, shape={audio.shape}, duration={len(audio)/24000:.2f}s')
    assert audio.dtype == np.float32
    assert 12000 < len(audio) < 120000
    a.release()
    print('PASSED')
    "
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_clipcannon_adapter.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import asyncio, numpy as np
from voiceagent.adapters.clipcannon import ClipCannonAdapter
a = ClipCannonAdapter('boris')
audio = asyncio.run(a.synthesize('Hello world'))
print(f'dtype={audio.dtype}, samples={len(audio)}, duration={len(audio)/24000:.2f}s')
assert audio.dtype == np.float32 and len(audio) > 12000
a.release()
print('OK')
"</command>
</test_commands>
</task_spec>
```
