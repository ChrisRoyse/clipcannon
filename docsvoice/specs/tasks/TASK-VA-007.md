```xml
<task_spec id="TASK-VA-007" version="2.0">
<metadata>
  <title>LLM Brain -- Qwen3-14B-FP8 Loader via vLLM with Streaming Generation</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>7</sequence>
  <implements>
    <item ref="PHASE1-LLM-BRAIN">LLMBrain class with generate_stream()</item>
    <item ref="PHASE1-LLM-LOAD">Qwen3-14B-FP8 model loading via vLLM</item>
    <item ref="PHASE1-VERIFY-1">Qwen3-14B loads to GPU (verification #1)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
  </depends_on>
  <estimated_complexity>high</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Implements the LLM reasoning engine for the voice agent. Loads Qwen3-14B-FP8 via
vLLM for efficient FP8 inference with continuous batching. The generate_stream()
method takes a list of chat messages and yields tokens as an async iterator. This
is the "thinking" core of the pipeline -- it sits between ASR (input text) and TTS
(output speech). The ContextManager (TASK-VA-009) builds the message list, and the
StreamingTTS (TASK-VA-012) consumes the token stream.

CRITICAL DETAILS:
- Model path: /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/
- Loading: vLLM preferred
    from vllm import LLM, SamplingParams
    LLM(model=path, quantization="fp8", gpu_memory_utilization=0.45, max_model_len=32768)
- Fallback: if vLLM import fails, use transformers AutoModelForCausalLM.from_pretrained.
    BUT: raise a clear WARNING (not silent). Log: "vLLM not available, falling back to
    transformers. Performance will be degraded."
- generate_stream(messages: list[dict]) -> AsyncIterator[str] -- streams tokens
- release() -> None -- unload model, clear VRAM, call torch.cuda.empty_cache()
- REQUIRES GPU. Tests MUST ERROR if GPU unavailable -- NEVER silently pass.
- After load: torch.cuda.memory_allocated() should be >5GB
- After release: torch.cuda.memory_allocated() should be ~0 (within tolerance)

Hardware: RTX 5090 (32GB GDDR7), CUDA 13.1/13.2, Python 3.12+
Project state: src/voiceagent/ does NOT exist yet -- 100% greenfield.
All imports require PYTHONPATH=src from repo root.
</context>

<input_context_files>
  <file purpose="llm_spec">docsvoice/01_phase1_core_pipeline.md#section-3.1</file>
  <file purpose="config">src/voiceagent/config.py (from TASK-VA-002: LLMConfig)</file>
  <file purpose="errors">src/voiceagent/errors.py (from TASK-VA-001: LLMError)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-002 complete (LLMConfig available in src/voiceagent/config.py)</check>
  <check>vllm installed: pip install vllm (preferred)</check>
  <check>transformers installed: pip install transformers (fallback only)</check>
  <check>Qwen3-14B-FP8 model available at /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/</check>
  <check>CUDA GPU available (RTX 5090, 32GB GDDR7)</check>
</prerequisites>

<scope>
  <in_scope>
    - LLMBrain class in src/voiceagent/brain/llm.py
    - __init__(config) loads model via vLLM with FP8 quantization
    - Fallback to transformers if vLLM import fails (with explicit WARNING log)
    - generate_stream(messages) yields tokens as AsyncIterator[str]
    - _build_chat_prompt(messages) converts message list to prompt string via tokenizer template
    - release() frees GPU memory, calls torch.cuda.empty_cache()
    - Configurable gpu_memory_utilization, max_model_len, max_tokens
    - Tests with REAL model on REAL GPU -- NO MOCKS
  </in_scope>
  <out_of_scope>
    - System prompt building (TASK-VA-008)
    - Context window management (TASK-VA-009)
    - Tool calling (Phase 4+)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/brain/llm.py">
      class LLMBrain:
          def __init__(self, config: LLMConfig) -> None: ...
          async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...
          def _build_chat_prompt(self, messages: list[dict[str, str]]) -> str: ...
          def release(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - PRIMARY: Model loaded via vLLM LLM class with quantization="fp8"
    - FALLBACK: If `from vllm import LLM` raises ImportError, use transformers
      AutoModelForCausalLM.from_pretrained with torch_dtype=torch.float16.
      Log a WARNING: "vLLM not available, falling back to transformers."
    - Model path: /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/
    - gpu_memory_utilization: 0.45 (vLLM only)
    - max_model_len: 32768
    - generate_stream uses SamplingParams with max_tokens from config (default 512), temperature=0.7, top_p=0.9
    - _build_chat_prompt uses tokenizer's apply_chat_template (Qwen3 chat format)
    - Raise LLMError if model fails to load (both paths)
    - release() deletes model, runs gc.collect(), calls torch.cuda.empty_cache()
    - generate_stream must be async (yields str tokens)
    - REQUIRES GPU -- tests MUST ERROR if GPU unavailable, NEVER silently pass
    - NO MOCKS -- tests load real model, generate real text
    - FAIL FAST -- no silent error swallowing
    - NO BACKWARDS COMPATIBILITY -- no fallbacks beyond the vLLM->transformers one
  </constraints>

  <verification>
    - LLMBrain instantiates and loads model to GPU
    - torch.cuda.memory_allocated() > 5GB after load (model is ~14B params in FP8 = ~14GB)
    - generate_stream yields non-empty string tokens for "Say hello"
    - _build_chat_prompt produces valid Qwen3 chat-formatted prompt string
    - release() frees GPU memory (torch.cuda.memory_allocated() drops significantly)
    - LLMError raised if model path doesn't exist
    - Tests ERROR if GPU unavailable
    - pytest tests/voiceagent/test_llm.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/brain/llm.py:
  """LLM Brain -- Qwen3-14B-FP8 reasoning engine.

  Loads Qwen3-14B-FP8 via vLLM (preferred) or transformers (fallback).
  Provides streaming token generation for the voice agent conversation loop.

  Usage:
      brain = LLMBrain(config)
      async for token in brain.generate_stream(messages):
          print(token, end="", flush=True)
      brain.release()
  """
  import gc
  import logging
  from collections.abc import AsyncIterator
  from voiceagent.errors import LLMError

  logger = logging.getLogger(__name__)

  class LLMBrain:
      def __init__(self, config) -> None:
          """Load LLM model.

          Args:
              config: LLMConfig with model_path, quantization, gpu_memory_utilization,
                      max_model_len, max_tokens.

          Raises:
              LLMError: If model fails to load via both vLLM and transformers.
          """
          self._config = config
          self._backend: str = "none"

          # Try vLLM first (preferred)
          try:
              from vllm import LLM, SamplingParams
              self._llm = LLM(
                  model=config.model_path,
                  quantization=config.quantization,  # "fp8"
                  gpu_memory_utilization=config.gpu_memory_utilization,  # 0.45
                  max_model_len=config.max_model_len,  # 32768
              )
              self._SamplingParams = SamplingParams
              self._backend = "vllm"
              logger.info("LLMBrain loaded via vLLM: %s", config.model_path)
          except ImportError:
              logger.warning(
                  "vLLM not available, falling back to transformers. "
                  "Performance will be degraded. Install vllm for optimal inference."
              )
              try:
                  import torch
                  from transformers import AutoModelForCausalLM, AutoTokenizer
                  self._hf_tokenizer = AutoTokenizer.from_pretrained(config.model_path)
                  self._hf_model = AutoModelForCausalLM.from_pretrained(
                      config.model_path,
                      torch_dtype=torch.float16,
                      device_map="auto",
                  )
                  self._backend = "transformers"
                  logger.info("LLMBrain loaded via transformers (fallback): %s", config.model_path)
              except Exception as e:
                  raise LLMError(
                      f"Failed to load LLM via transformers fallback: {e}. "
                      f"Model path: {config.model_path}. "
                      f"Ensure model exists and GPU has enough VRAM."
                  ) from e
          except Exception as e:
              raise LLMError(
                  f"Failed to load LLM via vLLM: {e}. "
                  f"Model path: {config.model_path}. "
                  f"Ensure vllm is installed and GPU has enough VRAM."
              ) from e

          # Load tokenizer for chat template (used by both backends)
          if self._backend == "vllm":
              from transformers import AutoTokenizer
              self._tokenizer = AutoTokenizer.from_pretrained(config.model_path)
          else:
              self._tokenizer = self._hf_tokenizer

      def _build_chat_prompt(self, messages: list[dict[str, str]]) -> str:
          """Convert chat messages to Qwen3 prompt format using tokenizer template.

          Args:
              messages: List of {"role": "system"|"user"|"assistant", "content": "..."}.

          Returns:
              Formatted prompt string ready for the model.

          Raises:
              LLMError: If messages list is empty.
          """
          if not messages:
              raise LLMError(
                  "Empty messages list. Provide at least one message with "
                  "'role' and 'content' keys."
              )
          return self._tokenizer.apply_chat_template(
              messages, tokenize=False, add_generation_prompt=True
          )

      async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
          """Stream tokens from the LLM given chat messages.

          Args:
              messages: List of {"role": "system"|"user"|"assistant", "content": "..."}.

          Yields:
              String tokens as they are generated.

          Raises:
              LLMError: If messages is empty or generation fails.
          """
          prompt = self._build_chat_prompt(messages)

          if self._backend == "vllm":
              params = self._SamplingParams(
                  max_tokens=self._config.max_tokens,
                  temperature=0.7,
                  top_p=0.9,
              )
              # vLLM generate() returns list of RequestOutput
              outputs = self._llm.generate([prompt], params)
              for output in outputs:
                  for completion in output.outputs:
                      yield completion.text

          elif self._backend == "transformers":
              import torch
              inputs = self._tokenizer(prompt, return_tensors="pt").to(self._hf_model.device)
              with torch.no_grad():
                  output_ids = self._hf_model.generate(
                      **inputs,
                      max_new_tokens=self._config.max_tokens,
                      temperature=0.7,
                      top_p=0.9,
                      do_sample=True,
                  )
              # Decode only the new tokens (exclude input)
              new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
              text = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
              yield text

          else:
              raise LLMError(
                  f"No backend loaded. Backend state: {self._backend}. "
                  f"This should never happen -- model loading failed silently."
              )

      def release(self) -> None:
          """Free GPU memory. Call when done with the LLM.

          After release, generate_stream will fail. Create a new LLMBrain instance
          to use the model again.
          """
          if self._backend == "vllm" and hasattr(self, '_llm'):
              del self._llm
          elif self._backend == "transformers" and hasattr(self, '_hf_model'):
              del self._hf_model
              if hasattr(self, '_hf_tokenizer'):
                  del self._hf_tokenizer

          if hasattr(self, '_tokenizer'):
              del self._tokenizer

          self._backend = "released"
          gc.collect()

          try:
              import torch
              torch.cuda.empty_cache()
              logger.info(
                  "LLMBrain released. VRAM after cleanup: %.1f MB",
                  torch.cuda.memory_allocated() / 1024 / 1024,
              )
          except ImportError:
              pass


tests/voiceagent/test_llm.py:
  """Tests for LLMBrain -- Qwen3-14B-FP8 reasoning engine.

  NO MOCKS -- uses real model on real GPU.
  REQUIRES GPU -- tests will ERROR (not silently pass) if GPU unavailable.

  Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_llm.py -v
  """
  import pytest
  import torch
  from voiceagent.brain.llm import LLMBrain
  from voiceagent.errors import LLMError

  MODEL_PATH = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"

  @pytest.fixture(scope="module")
  def check_gpu():
      """Verify CUDA GPU is available. ERROR if not -- do not silently skip."""
      if not torch.cuda.is_available():
          pytest.fail(
              "CUDA GPU required for LLMBrain tests. "
              "No GPU detected. This test must ERROR, not silently pass."
          )

  class LLMConfig:
      model_path = MODEL_PATH
      quantization = "fp8"
      gpu_memory_utilization = 0.45
      max_model_len = 32768
      max_tokens = 64  # Small for test speed

  @pytest.fixture(scope="module")
  def brain(check_gpu):
      """Load LLMBrain once for all tests (expensive operation)."""
      b = LLMBrain(LLMConfig())
      yield b
      b.release()

  def test_llm_loads_to_gpu(brain: LLMBrain, check_gpu) -> None:
      """Model should be loaded and consuming >5GB of VRAM."""
      vram_bytes = torch.cuda.memory_allocated()
      vram_gb = vram_bytes / (1024 ** 3)
      print(f"VRAM allocated: {vram_gb:.2f} GB")
      assert vram_gb > 5.0, (
          f"Expected >5GB VRAM after loading Qwen3-14B-FP8, got {vram_gb:.2f}GB. "
          f"Model may not have loaded correctly."
      )

  def test_build_chat_prompt(brain: LLMBrain) -> None:
      """_build_chat_prompt should produce Qwen3 chat template format."""
      messages = [
          {"role": "system", "content": "You are a helpful assistant."},
          {"role": "user", "content": "Hello"},
      ]
      prompt = brain._build_chat_prompt(messages)
      assert isinstance(prompt, str)
      assert len(prompt) > 0
      assert "Hello" in prompt
      print(f"Prompt preview: {prompt[:200]}...")

  def test_build_chat_prompt_empty_raises(brain: LLMBrain) -> None:
      """Empty messages list should raise LLMError."""
      with pytest.raises(LLMError, match="Empty messages list"):
          brain._build_chat_prompt([])

  @pytest.mark.asyncio
  async def test_generate_stream_yields_text(brain: LLMBrain) -> None:
      """generate_stream should yield non-empty text for a simple prompt."""
      messages = [
          {"role": "user", "content": "Say hello in one word."},
      ]
      tokens = []
      async for token in brain.generate_stream(messages):
          tokens.append(token)
      full_text = "".join(tokens)
      print(f"Generated text: {full_text[:200]}")
      assert len(full_text) > 0, "generate_stream yielded no text"

  @pytest.mark.asyncio
  async def test_generate_stream_empty_messages_raises(brain: LLMBrain) -> None:
      """Empty messages should raise LLMError."""
      with pytest.raises(LLMError, match="Empty messages list"):
          async for _ in brain.generate_stream([]):
              pass

  def test_llm_error_on_bad_model_path(check_gpu) -> None:
      """LLMError should be raised for nonexistent model path."""
      class BadConfig:
          model_path = "/nonexistent/path/to/model"
          quantization = "fp8"
          gpu_memory_utilization = 0.45
          max_model_len = 32768
          max_tokens = 64
      with pytest.raises(LLMError):
          LLMBrain(BadConfig())

  def test_release_frees_memory(check_gpu) -> None:
      """release() should free GPU memory significantly."""
      brain = LLMBrain(LLMConfig())
      vram_before = torch.cuda.memory_allocated()
      brain.release()
      vram_after = torch.cuda.memory_allocated()
      freed_gb = (vram_before - vram_after) / (1024 ** 3)
      print(f"VRAM freed by release(): {freed_gb:.2f} GB")
      print(f"VRAM remaining: {vram_after / (1024**3):.2f} GB")
      # After release, VRAM should have dropped significantly
      # (may not be exactly 0 due to CUDA context overhead)
      assert vram_after < vram_before, (
          f"release() did not free memory. Before: {vram_before}, After: {vram_after}"
      )
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/brain/llm.py">LLMBrain class with vLLM + transformers fallback</file>
  <file path="tests/voiceagent/test_llm.py">LLM tests with real model on real GPU</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>LLMBrain loads Qwen3-14B-FP8 model to GPU via vLLM</criterion>
  <criterion>torch.cuda.memory_allocated() > 5GB after model load</criterion>
  <criterion>generate_stream yields non-empty text tokens</criterion>
  <criterion>_build_chat_prompt produces valid Qwen3 chat template format</criterion>
  <criterion>LLMError raised for empty messages list</criterion>
  <criterion>LLMError raised for nonexistent model path</criterion>
  <criterion>release() frees GPU memory (VRAM decreases)</criterion>
  <criterion>Tests ERROR (not skip) if GPU unavailable</criterion>
  <criterion>All tests pass with real model on real GPU -- NO MOCKS</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_llm.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import torch
from voiceagent.brain.llm import LLMBrain

class Cfg:
    model_path = '/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/'
    quantization = 'fp8'
    gpu_memory_utilization = 0.45
    max_model_len = 32768
    max_tokens = 32

brain = LLMBrain(Cfg())
vram_gb = torch.cuda.memory_allocated() / (1024**3)
print(f'VRAM after load: {vram_gb:.2f} GB')
assert vram_gb > 5.0, f'Expected >5GB, got {vram_gb:.2f}GB'

import asyncio
async def test():
    text = []
    async for token in brain.generate_stream([{'role': 'user', 'content': 'Say hello'}]):
        text.append(token)
    return ''.join(text)
result = asyncio.run(test())
print(f'Generated: {result[:100]}')
assert len(result) > 0

brain.release()
vram_after = torch.cuda.memory_allocated() / (1024**3)
print(f'VRAM after release: {vram_after:.2f} GB')
print('LLMBrain OK')
"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    1. Model in VRAM: `torch.cuda.memory_allocated()` should be >5GB after __init__
    2. Generated text: the concatenation of all tokens yielded by generate_stream()
    3. VRAM after release: `torch.cuda.memory_allocated()` should drop significantly
    4. Backend: `brain._backend` should be "vllm" (preferred) or "transformers" (fallback)
  </source_of_truth>
  <execute_and_inspect>
    1. Load: brain = LLMBrain(config)
    2. Verify GPU memory: assert torch.cuda.memory_allocated() > 5 * 1024**3
    3. Verify backend: assert brain._backend in ("vllm", "transformers")
    4. Generate: tokens = [t async for t in brain.generate_stream(messages)]
    5. Verify output: assert len("".join(tokens)) > 0
    6. Release: brain.release()
    7. Verify cleanup: assert torch.cuda.memory_allocated() < vram_before_release
    8. Verify state: assert brain._backend == "released"
  </execute_and_inspect>
  <edge_case_audit>
    Edge Case 1: Empty messages list
      BEFORE: messages = []
      AFTER:  LLMError raised with message "Empty messages list. Provide at least one message."

    Edge Case 2: Very long input (>30K tokens)
      BEFORE: messages = [{"role": "user", "content": "x" * 100000}]
      AFTER:  Model processes up to max_model_len (32768 tokens). If input exceeds limit,
              vLLM will truncate or error. The error should propagate as LLMError or be
              handled by vLLM's internal limits.

    Edge Case 3: Model path doesn't exist
      BEFORE: config.model_path = "/nonexistent/path/to/model"
      AFTER:  LLMError raised with message containing the bad path and guidance to check it.

    Edge Case 4: GPU unavailable
      BEFORE: No CUDA GPU detected
      AFTER:  Test must ERROR with pytest.fail(), not silently pass or skip.
              LLMBrain.__init__ will raise LLMError during model loading.
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import torch
    print('GPU available:', torch.cuda.is_available())
    if not torch.cuda.is_available():
        print('ERROR: No GPU detected. Tests will fail.')
        exit(1)

    from voiceagent.brain.llm import LLMBrain

    class Cfg:
        model_path = '/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/'
        quantization = 'fp8'
        gpu_memory_utilization = 0.45
        max_model_len = 32768
        max_tokens = 32

    brain = LLMBrain(Cfg())
    vram_gb = torch.cuda.memory_allocated() / (1024**3)
    print(f'PASS: Model loaded. VRAM: {vram_gb:.2f} GB (expected >5)')
    print(f'PASS: Backend: {brain._backend}')

    prompt = brain._build_chat_prompt([{'role': 'user', 'content': 'Hello'}])
    print(f'PASS: Chat prompt built ({len(prompt)} chars)')

    import asyncio
    async def gen():
        tokens = []
        async for t in brain.generate_stream([{'role': 'user', 'content': 'Say hello'}]):
            tokens.append(t)
        return ''.join(tokens)
    result = asyncio.run(gen())
    print(f'PASS: Generated text: {result[:100]}')

    vram_before = torch.cuda.memory_allocated()
    brain.release()
    vram_after = torch.cuda.memory_allocated()
    print(f'PASS: Released. VRAM freed: {(vram_before - vram_after) / (1024**3):.2f} GB')
    print(f'PASS: Backend after release: {brain._backend}')
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  Input 1: messages = [{"role": "user", "content": "Say hello in one word."}]
    Expected: generate_stream yields non-empty text containing a greeting
    Expected VRAM: >5GB during generation

  Input 2: messages = []
    Expected: LLMError raised with "Empty messages list"

  Input 3: messages = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "What is 2+2?"}]
    Expected: generate_stream yields text containing "4"

  Input 4: config.model_path = "/nonexistent/path"
    Expected: LLMError raised during __init__

  Input 5: After release()
    Expected: torch.cuda.memory_allocated() < value before release
    Expected: brain._backend == "released"
</synthetic_test_data>

<manual_verification>
  Step 1: Verify GPU is available
    Run: python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')"
    Expected: CUDA: True, Device: NVIDIA GeForce RTX 5090 (or similar)

  Step 2: Verify model path exists
    Run: ls -la /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/
    Expected: Directory listing with model files (config.json, model weights, tokenizer files)

  Step 3: Verify LLMBrain loads
    Run: PYTHONPATH=src python -c "
    from voiceagent.brain.llm import LLMBrain
    class C:
        model_path='/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/'
        quantization='fp8'; gpu_memory_utilization=0.45; max_model_len=32768; max_tokens=32
    b = LLMBrain(C())
    print('Backend:', b._backend)
    b.release()
    "
    Expected: Prints "Backend: vllm" (or "transformers" if vLLM not installed)

  Step 4: Verify VRAM usage
    Run: PYTHONPATH=src python -c "
    import torch
    from voiceagent.brain.llm import LLMBrain
    class C:
        model_path='/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/'
        quantization='fp8'; gpu_memory_utilization=0.45; max_model_len=32768; max_tokens=32
    b = LLMBrain(C())
    print(f'VRAM: {torch.cuda.memory_allocated()/(1024**3):.2f} GB')
    b.release()
    print(f'VRAM after release: {torch.cuda.memory_allocated()/(1024**3):.2f} GB')
    "
    Expected: VRAM >5GB after load, significantly less after release

  Step 5: Verify generation
    Run: PYTHONPATH=src python -c "
    import asyncio
    from voiceagent.brain.llm import LLMBrain
    class C:
        model_path='/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/'
        quantization='fp8'; gpu_memory_utilization=0.45; max_model_len=32768; max_tokens=32
    b = LLMBrain(C())
    async def go():
        async for t in b.generate_stream([{'role':'user','content':'Say hello'}]):
            print(t, end='')
        print()
    asyncio.run(go())
    b.release()
    "
    Expected: Prints a greeting response

  Step 6: Run full test suite
    Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_llm.py -v
    Expected: All tests pass (requires GPU and model)
</manual_verification>
</task_spec>
```
