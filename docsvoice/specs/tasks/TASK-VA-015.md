```xml
<task_spec id="TASK-VA-015" version="2.0">
<metadata>
  <title>Hotkey Activator -- pynput Global Hotkey for Push-to-Talk</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>15</sequence>
  <implements>
    <item ref="PHASE1-HOTKEY">HotkeyActivator with pynput for push-to-talk fallback</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Provides a push-to-talk fallback activation method using a global hotkey (Ctrl+Space
by default). Used when wake word detection is disabled or unreliable. The hotkey
fires a callback that transitions the conversation from IDLE to LISTENING. Uses
pynput for cross-platform global hotkey listening. The VoiceAgent orchestrator
(TASK-VA-018) wires the callback to the conversation manager.

This is 100% greenfield -- src/voiceagent/ does not exist yet. The implementing agent
must create all directories and files from scratch. Python 3.12+.

IMPORTANT: pynput requires X11 or Wayland on Linux. In headless environments (CI,
WSL2 without X server, Docker), pynput.keyboard will fail with "Xlib.error.DisplayNameError"
or similar. The code must handle this gracefully and document the limitation.
</context>

<input_context_files>
  <file purpose="hotkey_spec">docsvoice/01_phase1_core_pipeline.md#section-7.2</file>
  <file purpose="package_structure">src/voiceagent/activation/__init__.py (create if not exists)</file>
  <file purpose="errors">src/voiceagent/errors.py (create if not exists)</file>
</input_context_files>

<prerequisites>
  <check>Python 3.12+ available: python3 --version</check>
  <check>pynput installed: python3 -c "import pynput; print(pynput.__version__)"</check>
  <check>If pynput missing: pip install pynput</check>
  <check>If dirs missing, create: mkdir -p src/voiceagent/activation &amp;&amp; touch src/voiceagent/__init__.py src/voiceagent/activation/__init__.py</check>
</prerequisites>

<scope>
  <in_scope>
    - HotkeyActivator class in src/voiceagent/activation/hotkey.py
    - __init__(key_combo="&lt;ctrl&gt;+&lt;space&gt;", callback=None)
    - start() -- begins listening in background daemon thread
    - stop() -- stops the listener cleanly
    - The callback is called when hotkey is pressed
    - Graceful handling of headless/no-display environments
    - Unit tests (limited scope -- pynput hotkey press cannot be simulated in CI)
  </in_scope>
  <out_of_scope>
    - Wake word detection (TASK-VA-014)
    - Conversation state management (TASK-VA-013)
    - GUI/visual indicator of hotkey state
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/activation/hotkey.py">
      from typing import Callable

      class HotkeyActivator:
          def __init__(self, key_combo: str = "&lt;ctrl&gt;+&lt;space&gt;", callback: Callable[[], None] | None = None) -> None: ...
          def start(self) -> None: ...
          def stop(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - Uses pynput.keyboard.GlobalHotKeys for hotkey detection
    - key_combo format follows pynput convention (e.g., "&lt;ctrl&gt;+&lt;space&gt;")
    - start() launches listener as daemon thread (non-blocking)
    - stop() terminates the listener cleanly, sets _listener to None
    - callback is optional (can be None)
    - No-op if callback is None when hotkey fires
    - start() called twice: stop old listener first, then start new one
    - stop() called without start(): no-op, no crash
    - None callback: log warning, do not crash
    - Thread-safe: listener runs in background
    - If pynput is not installed: raise ImportError with "pip install pynput"
    - If display not available (headless/WSL2): raise VoiceAgentError with clear message explaining X11/Wayland requirement
    - All errors logged with what/why/how-to-fix pattern
  </constraints>

  <verification>
    - HotkeyActivator() instantiates without error (on systems with display)
    - start() does not block
    - stop() does not raise
    - start() twice does not leave zombie listeners
    - stop() without start() does not raise
    - None callback does not crash
    - pytest tests/voiceagent/test_hotkey.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/activation/hotkey.py:
  """Global hotkey activation for push-to-talk.

  IMPORTANT: pynput requires X11 or Wayland on Linux. In headless environments
  (CI, WSL2 without X server, Docker), this module will raise VoiceAgentError
  on start(). Use wake word detection (TASK-VA-014) as alternative.
  """
  import logging
  from typing import Callable

  logger = logging.getLogger(__name__)

  class HotkeyActivator:
      """Global hotkey listener for push-to-talk activation.

      Args:
          key_combo: pynput-format key combination (default "&lt;ctrl&gt;+&lt;space&gt;").
          callback: Function called when hotkey is pressed. Can be None.

      Example:
          activator = HotkeyActivator(callback=lambda: print("Activated!"))
          activator.start()
          # ... hotkey press triggers callback ...
          activator.stop()
      """

      def __init__(self, key_combo: str = "<ctrl>+<space>", callback: Callable[[], None] | None = None):
          try:
              import pynput  # noqa: F401
          except ImportError:
              raise ImportError(
                  "pynput is required for hotkey activation. "
                  "Install with: pip install pynput"
              )

          self.callback = callback
          self._key_combo = key_combo
          self._listener = None  # pynput.keyboard.GlobalHotKeys instance
          logger.info("HotkeyActivator created: key_combo=%s, callback=%s",
                      key_combo, "set" if callback else "None")

      def _on_activate(self):
          """Called when hotkey is pressed."""
          logger.info("Hotkey activated: %s", self._key_combo)
          if self.callback is None:
              logger.warning(
                  "Hotkey fired but callback is None. "
                  "Why: no callback was set. "
                  "Fix: pass callback= to constructor or set activator.callback = func"
              )
              return
          try:
              self.callback()
          except Exception as e:
              logger.error(
                  "Hotkey callback raised exception: %s. "
                  "Why: the callback function failed. "
                  "Fix: check the callback implementation.",
                  e,
              )

      def start(self) -> None:
          """Begin listening for hotkey in background daemon thread.

          Raises:
              VoiceAgentError: If display is not available (headless/WSL2).
          """
          # If already running, stop first
          if self._listener is not None:
              logger.warning("start() called while already running. Stopping old listener first.")
              self.stop()

          try:
              from pynput.keyboard import GlobalHotKeys
              self._listener = GlobalHotKeys({self._key_combo: self._on_activate})
              self._listener.daemon = True
              self._listener.start()
              logger.info("Hotkey listener started: %s", self._key_combo)
          except Exception as e:
              self._listener = None
              from voiceagent.errors import VoiceAgentError
              raise VoiceAgentError(
                  f"Failed to start hotkey listener. "
                  f"What: pynput could not initialize keyboard listener. "
                  f"Why: {e}. "
                  f"Fix: pynput requires X11 or Wayland on Linux. "
                  f"In WSL2, install an X server (e.g., VcXsrv) and set DISPLAY=:0. "
                  f"In Docker, use --env DISPLAY and mount /tmp/.X11-unix. "
                  f"Alternative: use wake word detection instead of hotkey."
              ) from e

      def stop(self) -> None:
          """Stop the hotkey listener. No-op if not running."""
          if self._listener is None:
              logger.debug("stop() called but no listener running (no-op)")
              return
          try:
              self._listener.stop()
              logger.info("Hotkey listener stopped")
          except Exception as e:
              logger.warning("Error stopping hotkey listener: %s", e)
          finally:
              self._listener = None

tests/voiceagent/test_hotkey.py:
  """Tests for hotkey activator.

  NOTE: pynput requires X11/Wayland for GlobalHotKeys. Tests that call start()
  are marked with @pytest.mark.skipif for headless environments. Actual hotkey
  press simulation is NOT possible in automated tests -- those are manual.
  """
  import os
  import pytest

  pynput = pytest.importorskip("pynput", reason="pynput not installed")

  from voiceagent.activation.hotkey import HotkeyActivator

  # Detect headless environment
  HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

  def test_hotkey_instantiates():
      """Constructor should work without display (no listener started yet)."""
      activator = HotkeyActivator()
      assert activator._key_combo == "<ctrl>+<space>"
      assert activator.callback is None
      assert activator._listener is None

  def test_hotkey_instantiates_with_callback():
      flag = []
      activator = HotkeyActivator(callback=lambda: flag.append(True))
      assert activator.callback is not None

  def test_hotkey_custom_key_combo():
      activator = HotkeyActivator(key_combo="<ctrl>+<alt>+p")
      assert activator._key_combo == "<ctrl>+<alt>+p"

  def test_stop_without_start_is_noop():
      """stop() before start() must not raise."""
      activator = HotkeyActivator()
      activator.stop()  # Should not raise
      assert activator._listener is None

  def test_stop_called_twice_is_safe():
      """Double stop must not raise."""
      activator = HotkeyActivator()
      activator.stop()
      activator.stop()

  @pytest.mark.skipif(not HAS_DISPLAY, reason="No display available (headless/WSL2)")
  def test_start_does_not_block():
      """start() should return immediately (daemon thread)."""
      activator = HotkeyActivator()
      try:
          activator.start()
          assert activator._listener is not None
      finally:
          activator.stop()

  @pytest.mark.skipif(not HAS_DISPLAY, reason="No display available (headless/WSL2)")
  def test_start_twice_stops_old_listener():
      """Calling start() twice should stop the old listener first."""
      activator = HotkeyActivator()
      try:
          activator.start()
          first_listener = activator._listener
          activator.start()
          assert activator._listener is not first_listener
      finally:
          activator.stop()

  @pytest.mark.skipif(HAS_DISPLAY, reason="Test only runs in headless environment")
  def test_start_headless_raises_voice_agent_error():
      """In headless environment, start() should raise with clear message."""
      from voiceagent.errors import VoiceAgentError
      activator = HotkeyActivator()
      with pytest.raises(VoiceAgentError, match="pynput"):
          activator.start()

  def test_on_activate_with_none_callback(caplog):
      """Firing hotkey with None callback should log warning, not crash."""
      activator = HotkeyActivator(callback=None)
      activator._on_activate()  # Direct call, no actual hotkey
      assert "callback is None" in caplog.text

  def test_on_activate_with_callback():
      """Callback should be invoked when _on_activate is called."""
      flag = []
      activator = HotkeyActivator(callback=lambda: flag.append(True))
      activator._on_activate()
      assert flag == [True]

  def test_on_activate_callback_exception_handled(caplog):
      """If callback raises, it should be caught and logged."""
      def bad_callback():
          raise RuntimeError("boom")
      activator = HotkeyActivator(callback=bad_callback)
      activator._on_activate()  # Should not raise
      assert "callback raised exception" in caplog.text

  # Manual test instructions (cannot be automated):
  # 1. Run: PYTHONPATH=src python -c "
  #    from voiceagent.activation.hotkey import HotkeyActivator
  #    import time
  #    flag = []
  #    h = HotkeyActivator(callback=lambda: (flag.append(True), print('ACTIVATED!')))
  #    h.start()
  #    print('Press Ctrl+Space within 10 seconds...')
  #    time.sleep(10)
  #    h.stop()
  #    print('Detected:', len(flag), 'activations')
  #    "
  # 2. Press Ctrl+Space during the 10-second window
  # 3. Verify "ACTIVATED!" is printed
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/activation/hotkey.py">HotkeyActivator class</file>
  <file path="tests/voiceagent/test_hotkey.py">Unit tests for hotkey activator</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<full_state_verification>
  <source_of_truth>
    1. activator._listener: None means stopped, non-None means running.
    2. Callback invocation: the callback function's side effects (e.g., flag list).
    These are the ONLY places to check hotkey state.
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create HotkeyActivator with a callback that appends to a list.
    Step 2: Call start() (if display available).
    Step 3: Verify _listener is not None.
    Step 4: Call _on_activate() directly to test callback path.
    Step 5: Verify flag list has expected content.
    Step 6: Call stop(), verify _listener is None.
  </execute_and_inspect>

  <edge_case_audit>
    <case name="start_called_twice">
      <before>activator._listener is some_listener_A</before>
      <action>activator.start()</action>
      <after>some_listener_A is stopped, activator._listener is a NEW listener_B</after>
    </case>
    <case name="stop_without_start">
      <before>activator._listener is None (never started)</before>
      <action>activator.stop()</action>
      <after>No error raised, _listener still None</after>
    </case>
    <case name="none_callback_hotkey_fires">
      <before>activator.callback is None</before>
      <action>activator._on_activate()</action>
      <after>Warning logged "callback is None", no crash</after>
    </case>
    <case name="callback_raises_exception">
      <before>activator.callback = lambda: 1/0</before>
      <action>activator._on_activate()</action>
      <after>Error logged "callback raised exception", no crash, listener still running</after>
    </case>
    <case name="headless_environment">
      <before>No DISPLAY env var, no X11</before>
      <action>activator.start()</action>
      <after>VoiceAgentError raised with message about X11/Wayland requirement and WSL2 fix</after>
    </case>
  </edge_case_audit>

  <evidence_of_success>
    cd /home/cabdru/clipcannon

    PYTHONPATH=src python -c "
from voiceagent.activation.hotkey import HotkeyActivator
h = HotkeyActivator()
print('Created OK, key_combo:', h._key_combo)
h.stop()  # no-op
print('stop() without start() OK')
"

    PYTHONPATH=src python -c "
from voiceagent.activation.hotkey import HotkeyActivator
flag = []
h = HotkeyActivator(callback=lambda: flag.append(True))
h._on_activate()
assert flag == [True], f'Expected [True] got {flag}'
print('PASS: callback invoked')
"

    PYTHONPATH=src python -m pytest tests/voiceagent/test_hotkey.py -v --tb=short
    # All non-skipped tests must pass
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="constructor_defaults">
    <input>HotkeyActivator()</input>
    <expected>_key_combo == "&lt;ctrl&gt;+&lt;space&gt;", callback == None, _listener == None</expected>
  </test>
  <test name="callback_invocation">
    <input>HotkeyActivator(callback=lambda: flag.append(True)), then _on_activate()</input>
    <expected>flag == [True]</expected>
  </test>
  <test name="none_callback_no_crash">
    <input>HotkeyActivator(callback=None), then _on_activate()</input>
    <expected>No exception raised, warning logged</expected>
  </test>
  <test name="stop_noop">
    <input>HotkeyActivator(), then stop()</input>
    <expected>No exception raised, _listener still None</expected>
  </test>
</synthetic_test_data>

<manual_verification>
  <step>1. cd /home/cabdru/clipcannon</step>
  <step>2. Verify pynput installed: python3 -c "import pynput; print(pynput.__version__)"</step>
  <step>3. Verify file exists: ls -la src/voiceagent/activation/hotkey.py</step>
  <step>4. Verify import works: PYTHONPATH=src python -c "from voiceagent.activation.hotkey import HotkeyActivator; print('PASS')"</step>
  <step>5. Run tests: PYTHONPATH=src python -m pytest tests/voiceagent/test_hotkey.py -v --tb=short</step>
  <step>6. Verify callback path: PYTHONPATH=src python -c "
from voiceagent.activation.hotkey import HotkeyActivator
flag = []
h = HotkeyActivator(callback=lambda: flag.append(True))
h._on_activate()
assert flag == [True]
print('PASS: callback works')
"</step>
  <step>7. Verify NO mocks: grep -c "mock\|Mock\|MagicMock\|patch" tests/voiceagent/test_hotkey.py  # Should be 0</step>
  <step>8. MANUAL (requires display): Run interactive test from pseudo_code comments to verify actual hotkey detection</step>
</manual_verification>

<validation_criteria>
  <criterion>HotkeyActivator instantiates with default key combo</criterion>
  <criterion>start() launches non-blocking daemon listener (when display available)</criterion>
  <criterion>stop() cleanly terminates listener</criterion>
  <criterion>start() called twice stops old listener first</criterion>
  <criterion>stop() without start() is no-op</criterion>
  <criterion>None callback logs warning, does not crash</criterion>
  <criterion>Callback exception caught and logged, does not crash</criterion>
  <criterion>Headless environment raises VoiceAgentError with clear fix instructions</criterion>
  <criterion>Missing pynput raises ImportError with install instructions</criterion>
  <criterion>All non-skipped tests pass</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -m pytest tests/voiceagent/test_hotkey.py -v --tb=short</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.activation.hotkey import HotkeyActivator; h = HotkeyActivator(); print('Hotkey OK')"</command>
</test_commands>
</task_spec>
```
