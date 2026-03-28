```xml
<task_spec id="TASK-VA-001" version="2.0">
<metadata>
  <title>Project Scaffolding -- Create Package Structure and Error Types</title>
  <status>ready</status>
  <layer>foundation</layer>
  <sequence>1</sequence>
  <implements>
    <item ref="PHASE1-SCAFFOLD">Package structure with all subpackages</item>
    <item ref="PHASE1-ERRORS">Custom exception hierarchy for all subsystems</item>
  </implements>
  <depends_on>
    <!-- None -- first task -->
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>10 files</estimated_files>
</metadata>

<context>
This is the very first task for the Voice Agent. Nothing exists yet -- src/voiceagent/
does not exist at all. This task creates the entire directory structure under
src/voiceagent/ with __init__.py files for every subpackage and the shared errors.py
module. All subsequent tasks depend on this scaffolding existing.

No business logic is implemented here -- only empty __init__.py files (with docstrings)
and the exception class hierarchy in errors.py.

IMPORTANT: The working directory is /home/cabdru/clipcannon. The existing ClipCannon
project lives at src/clipcannon/ -- DO NOT modify anything in that directory. The voice
agent is a SEPARATE package at src/voiceagent/.

IMPORTANT: Python 3.12+ is required (NOT 3.11).

IMPORTANT: All import/run commands MUST use PYTHONPATH=src because src/voiceagent/ is
not an installed package. Example:
  cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent"
</context>

<input_context_files>
  <file purpose="directory_structure">docsvoice/01_phase1_core_pipeline.md#section-1.1</file>
  <file purpose="project_layout">docsvoice/00_implementation_index.md</file>
</input_context_files>

<prerequisites>
  <check>Python 3.12+ available: python3 --version must show 3.12 or higher</check>
  <check>src/ directory exists: ls /home/cabdru/clipcannon/src/ must succeed</check>
  <check>src/voiceagent/ does NOT exist yet: ls /home/cabdru/clipcannon/src/voiceagent/ must FAIL</check>
</prerequisites>

<scope>
  <in_scope>
    - Create src/voiceagent/__init__.py with __version__ = "0.1.0"
    - Create src/voiceagent/errors.py with ALL exception classes listed below
    - Create __init__.py for EXACTLY these subpackages: asr, brain, conversation, tts, transport, adapters, activation, db
    - Each subpackage __init__.py has a docstring and nothing else
  </in_scope>
  <out_of_scope>
    - memory/ subpackage -- Phase 1 does NOT use memory. Do NOT create it.
    - eval/ subpackage -- Phase 1 does NOT use eval. Do NOT create it.
    - Configuration loading (TASK-VA-002)
    - Database schema (TASK-VA-003)
    - Any business logic modules
    - Test files (errors are trivial exception subclasses; testing is via import verification)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/__init__.py">
      """Voice Agent -- Personal AI Assistant."""
      __version__ = "0.1.0"
    </signature>
    <signature file="src/voiceagent/errors.py">
      """Custom exception hierarchy for the Voice Agent.

      All voice agent exceptions inherit from VoiceAgentError.
      Subsystem-specific exceptions are organized by domain.
      """

      class VoiceAgentError(Exception):
          """Base exception for all voice agent errors."""

      class ConfigError(VoiceAgentError):
          """Raised when configuration is invalid or missing."""

      class ASRError(VoiceAgentError):
          """Raised when ASR (speech recognition) fails."""

      class VADError(ASRError):
          """Raised when VAD (voice activity detection) fails. Subclass of ASRError."""

      class LLMError(VoiceAgentError):
          """Raised when LLM inference fails."""

      class TTSError(VoiceAgentError):
          """Raised when TTS (text-to-speech) synthesis fails."""

      class TransportError(VoiceAgentError):
          """Raised when WebSocket transport fails."""

      class DatabaseError(VoiceAgentError):
          """Raised when database operations fail."""

      class WakeWordError(VoiceAgentError):
          """Raised when wake word detection fails."""

      class ActivationError(VoiceAgentError):
          """Raised when voice activation (wake word or push-to-talk) fails."""

      class ModelLoadError(VoiceAgentError):
          """Raised when a GPU model fails to load (VRAM, path, or compatibility issues)."""

      class ConversationError(VoiceAgentError):
          """Raised when conversation state machine encounters an invalid transition."""
    </signature>
  </signatures>

  <constraints>
    - All exceptions inherit from VoiceAgentError base class
    - VADError is a subclass of ASRError (VAD is part of ASR subsystem)
    - All other exceptions are direct subclasses of VoiceAgentError
    - Each exception class has a docstring explaining when it is raised
    - No external dependencies -- only stdlib
    - Follow Python naming conventions: PascalCase for classes
    - Every __init__.py has a module docstring
    - Python 3.12+ syntax only
    - EXACTLY 8 subpackages: asr, brain, conversation, tts, transport, adapters, activation, db
    - NO memory/, eval/, or any other subpackages
  </constraints>

  <verification>
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent import __version__; print(__version__)" outputs "0.1.0"
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import VoiceAgentError, ASRError, VADError, LLMError, TTSError, ConfigError, TransportError, DatabaseError, WakeWordError, ActivationError, ModelLoadError, ConversationError; print('All 11 error classes imported')"
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import VADError, ASRError; assert issubclass(VADError, ASRError); print('VADError inherits ASRError')"
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent.asr, voiceagent.brain, voiceagent.conversation, voiceagent.tts, voiceagent.transport, voiceagent.adapters, voiceagent.activation, voiceagent.db; print('All 8 subpackages imported')"
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/__init__.py:
  """Voice Agent -- Personal AI Assistant."""
  __version__ = "0.1.0"

src/voiceagent/errors.py:
  """Custom exception hierarchy for the Voice Agent.

  All voice agent exceptions inherit from VoiceAgentError.
  Subsystem-specific exceptions are organized by domain.
  """

  class VoiceAgentError(Exception):
      """Base exception for all voice agent errors."""

  class ConfigError(VoiceAgentError):
      """Raised when configuration is invalid or missing."""

  class ASRError(VoiceAgentError):
      """Raised when ASR (speech recognition) fails."""

  class VADError(ASRError):
      """Raised when VAD (voice activity detection) fails. Subclass of ASRError."""

  class LLMError(VoiceAgentError):
      """Raised when LLM inference fails."""

  class TTSError(VoiceAgentError):
      """Raised when TTS (text-to-speech) synthesis fails."""

  class TransportError(VoiceAgentError):
      """Raised when WebSocket transport fails."""

  class DatabaseError(VoiceAgentError):
      """Raised when database operations fail."""

  class WakeWordError(VoiceAgentError):
      """Raised when wake word detection fails."""

  class ActivationError(VoiceAgentError):
      """Raised when voice activation (wake word or push-to-talk) fails."""

  class ModelLoadError(VoiceAgentError):
      """Raised when a GPU model fails to load (VRAM, path, or compatibility issues)."""

  class ConversationError(VoiceAgentError):
      """Raised when conversation state machine encounters an invalid transition."""

Each subpackage __init__.py (asr, brain, conversation, tts, transport, adapters, activation, db):
  """Voice Agent {subpackage_name} module."""
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/__init__.py">Package root with __version__ = "0.1.0"</file>
  <file path="src/voiceagent/errors.py">Exception class hierarchy (11 classes)</file>
  <file path="src/voiceagent/asr/__init__.py">ASR subpackage init</file>
  <file path="src/voiceagent/brain/__init__.py">Brain subpackage init</file>
  <file path="src/voiceagent/conversation/__init__.py">Conversation subpackage init</file>
  <file path="src/voiceagent/tts/__init__.py">TTS subpackage init</file>
  <file path="src/voiceagent/transport/__init__.py">Transport subpackage init</file>
  <file path="src/voiceagent/adapters/__init__.py">Adapters subpackage init</file>
  <file path="src/voiceagent/activation/__init__.py">Activation subpackage init</file>
  <file path="src/voiceagent/db/__init__.py">Database subpackage init</file>
</files_to_create>

<files_to_modify>
  <!-- None -- all new files -->
</files_to_modify>

<validation_criteria>
  <criterion>All 10 files exist (1 root __init__.py, 1 errors.py, 8 subpackage __init__.py)</criterion>
  <criterion>errors.py defines exactly 11 exception classes with proper inheritance</criterion>
  <criterion>VADError inherits from ASRError, all others inherit from VoiceAgentError</criterion>
  <criterion>No external dependencies required</criterion>
  <criterion>All imports succeed with PYTHONPATH=src</criterion>
  <criterion>NO memory/, eval/, or other subpackages exist</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent import __version__; assert __version__ == '0.1.0'; print('OK: version is 0.1.0')"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import VoiceAgentError, ASRError, VADError, LLMError, TTSError, ConfigError, TransportError, DatabaseError, WakeWordError, ActivationError, ModelLoadError, ConversationError; print('OK: All 11 error classes imported')"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import VADError, ASRError; assert issubclass(VADError, ASRError); print('OK: VADError is subclass of ASRError')"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent.asr, voiceagent.brain, voiceagent.conversation, voiceagent.tts, voiceagent.transport, voiceagent.adapters, voiceagent.activation, voiceagent.db; print('OK: All 8 subpackages imported')"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    Files on disk under /home/cabdru/clipcannon/src/voiceagent/.
    After task completion, these files MUST exist:
      src/voiceagent/__init__.py
      src/voiceagent/errors.py
      src/voiceagent/asr/__init__.py
      src/voiceagent/brain/__init__.py
      src/voiceagent/conversation/__init__.py
      src/voiceagent/tts/__init__.py
      src/voiceagent/transport/__init__.py
      src/voiceagent/adapters/__init__.py
      src/voiceagent/activation/__init__.py
      src/voiceagent/db/__init__.py
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create all directories and files.
    Step 2: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/` to prove root package exists.
    Step 3: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/*/` to prove all 8 subpackage dirs exist.
    Step 4: Run `find /home/cabdru/clipcannon/src/voiceagent/ -name "*.py" | sort` to list ALL .py files created.
    Step 5: Run each import command from <test_commands> to prove Python can import everything.
    Step 6: Run `ls /home/cabdru/clipcannon/src/voiceagent/memory/ 2>&1` -- must FAIL (directory must NOT exist).
    Step 7: Run `ls /home/cabdru/clipcannon/src/voiceagent/eval/ 2>&1` -- must FAIL (directory must NOT exist).
  </execute_and_inspect>

  <edge_case_audit>
    Edge case 1: Import with wrong module name
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import FakeError"
      Expected: ModuleNotFoundError or ImportError with message containing "FakeError"
      BEFORE: No src/voiceagent/ directory exists
      AFTER: Import fails with ImportError: cannot import name 'FakeError' from 'voiceagent.errors'

    Edge case 2: Import without PYTHONPATH
      Command: cd /tmp && python -c "import voiceagent"
      Expected: ModuleNotFoundError: No module named 'voiceagent'
      BEFORE: Same error
      AFTER: Same error -- voiceagent is NOT installed, requires PYTHONPATH=src

    Edge case 3: Import nonexistent subpackage (memory)
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent.memory"
      Expected: ModuleNotFoundError: No module named 'voiceagent.memory'
      BEFORE: No src/voiceagent/ exists at all
      AFTER: voiceagent exists but voiceagent.memory does NOT -- ModuleNotFoundError

    Edge case 4: Verify inheritance chain
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import VADError; print(VADError.__mro__)"
      Expected: (<class 'voiceagent.errors.VADError'>, <class 'voiceagent.errors.ASRError'>, <class 'voiceagent.errors.VoiceAgentError'>, <class 'Exception'>, <class 'BaseException'>, <class 'object'>)
  </edge_case_audit>

  <evidence_of_success>
    Command 1: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent; print(voiceagent.__version__)"
    Must print: 0.1.0

    Command 2: cd /home/cabdru/clipcannon && ls -la src/voiceagent/asr/__init__.py
    Must show: file exists with non-zero size

    Command 3: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.errors import (VoiceAgentError, ConfigError, ASRError, VADError,
    LLMError, TTSError, TransportError, DatabaseError, WakeWordError,
    ActivationError, ModelLoadError, ConversationError)
errors = [VoiceAgentError, ConfigError, ASRError, VADError, LLMError, TTSError,
    TransportError, DatabaseError, WakeWordError, ActivationError, ModelLoadError,
    ConversationError]
for e in errors:
    assert issubclass(e, VoiceAgentError), f'{e.__name__} does not inherit VoiceAgentError'
assert issubclass(VADError, ASRError), 'VADError must inherit ASRError'
print(f'All {len(errors)} error classes verified')
"
    Must print: All 12 error classes verified

    Command 4: cd /home/cabdru/clipcannon && find src/voiceagent/ -name "*.py" | wc -l
    Must print: 10

    Command 5: cd /home/cabdru/clipcannon && ls src/voiceagent/memory/ 2>&1
    Must print: ls: cannot access 'src/voiceagent/memory/': No such file or directory
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  No synthetic test data needed for this task -- it is pure scaffolding.
  The "test data" is the set of import statements that must succeed:

  Input: python -c "from voiceagent import __version__"
  Expected output: no error, __version__ == "0.1.0"

  Input: python -c "from voiceagent.errors import WakeWordError; raise WakeWordError('test')"
  Expected output: voiceagent.errors.WakeWordError: test

  Input: python -c "from voiceagent.errors import ModelLoadError; raise ModelLoadError('GPU OOM')"
  Expected output: voiceagent.errors.ModelLoadError: GPU OOM

  Input: python -c "from voiceagent.errors import ConversationError; raise ConversationError('invalid state')"
  Expected output: voiceagent.errors.ConversationError: invalid state
</synthetic_test_data>

<manual_verification>
  The implementing agent MUST perform these checks AFTER creating all files:

  1. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/__init__.py
     Verify: File exists, non-zero size

  2. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/errors.py
     Verify: File exists, non-zero size

  3. Run: ls -d /home/cabdru/clipcannon/src/voiceagent/*/
     Verify: Exactly 8 directories: asr, brain, conversation, tts, transport, adapters, activation, db
     Verify: NO memory/ or eval/ directories

  4. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent import __version__; print(__version__)"
     Verify: Prints "0.1.0"

  5. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.errors import (VoiceAgentError, ConfigError, ASRError, VADError,
    LLMError, TTSError, TransportError, DatabaseError, WakeWordError,
    ActivationError, ModelLoadError, ConversationError)
print('All imports OK')
assert issubclass(VADError, ASRError)
print('Inheritance OK')
"
     Verify: Both "All imports OK" and "Inheritance OK" printed

  6. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import voiceagent.asr
import voiceagent.brain
import voiceagent.conversation
import voiceagent.tts
import voiceagent.transport
import voiceagent.adapters
import voiceagent.activation
import voiceagent.db
print('All 8 subpackages OK')
"
     Verify: "All 8 subpackages OK" printed

  7. Run: cd /home/cabdru/clipcannon && ls src/voiceagent/memory/ 2>&1
     Verify: Error message -- directory must NOT exist

  8. Run: cd /home/cabdru/clipcannon && ls src/voiceagent/eval/ 2>&1
     Verify: Error message -- directory must NOT exist
</manual_verification>
</task_spec>
```
