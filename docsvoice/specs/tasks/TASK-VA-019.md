```xml
<task_spec id="TASK-VA-019" version="2.0">
<metadata>
  <title>CLI Entry Point -- voiceagent serve and voiceagent talk Commands</title>
  <status>ready</status>
  <layer>surface</layer>
  <sequence>19</sequence>
  <implements>
    <item ref="PHASE1-CLI">CLI with serve and talk commands via click</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-017</task_ref>
    <task_ref>TASK-VA-018</task_ref>
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>3 files</estimated_files>
</metadata>

<context>
Creates the command-line interface for the voice agent using the click library. Two commands:

- `voiceagent serve --voice boris --port 8765` -- starts the WebSocket/FastAPI server
  for remote clients. This instantiates VoiceAgent (TASK-VA-018) and calls start().

- `voiceagent talk --voice boris` -- starts an interactive local microphone conversation.
  This instantiates VoiceAgent (TASK-VA-018) and calls talk_interactive().

The CLI is the user-facing entry point for Phase 1. It is callable via:
- `python -m voiceagent serve ...`
- `python -m voiceagent talk ...`

The entry point is also configured in pyproject.toml so that `voiceagent` is a
command-line script after `pip install -e .`.

Hardware context:
- RTX 5090 GPU (32GB GDDR7), CUDA 13.1/13.2
- Python 3.12+, src/voiceagent/ is greenfield (does not exist yet)
- All imports: PYTHONPATH=src python -c "from voiceagent.cli import cli"
- Default voice: "boris" (Chris Royse's cloned voice, 0.975 SECS)
</context>

<input_context_files>
  <file purpose="cli_spec">docsvoice/01_phase1_core_pipeline.md#section-8</file>
  <file purpose="agent">src/voiceagent/agent.py</file>
  <file purpose="config">src/voiceagent/config.py</file>
  <file purpose="server">src/voiceagent/server.py</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-017 complete (FastAPI server available at src/voiceagent/server.py)</check>
  <check>TASK-VA-018 complete (VoiceAgent orchestrator available at src/voiceagent/agent.py)</check>
  <check>pip install click -- must be in the environment</check>
</prerequisites>

<scope>
  <in_scope>
    - CLI group in src/voiceagent/cli.py
    - `serve` command with --voice, --port, --host options
    - `talk` command with --voice option
    - Proper asyncio event loop handling
    - Signal handling for graceful shutdown (SIGINT, SIGTERM)
    - src/voiceagent/__main__.py for `python -m voiceagent` support
    - Tests using click.testing.CliRunner (this is OK -- testing the CLI framework, not mocking)
  </in_scope>
  <out_of_scope>
    - VoiceAgent implementation (TASK-VA-018)
    - FastAPI server implementation (TASK-VA-017)
    - Config file creation wizard
    - Daemon/service mode
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/cli.py">
      import click

      @click.group()
      def cli() -> None:
          """Voice Agent -- Personal AI Assistant."""
          ...

      @cli.command()
      @click.option("--voice", default="boris", help="ClipCannon voice profile name")
      @click.option("--port", default=8765, type=int, help="WebSocket port")
      @click.option("--host", default="0.0.0.0", help="Bind address")
      def serve(voice: str, port: int, host: str) -> None:
          """Start the voice agent server."""
          ...

      @cli.command()
      @click.option("--voice", default="boris", help="ClipCannon voice profile name")
      def talk(voice: str) -> None:
          """Interactive voice conversation using local microphone."""
          ...
    </signature>
    <signature file="src/voiceagent/__main__.py">
      from voiceagent.cli import cli
      cli()
    </signature>
  </signatures>

  <constraints>
    - Uses click for CLI framework (not argparse, not typer)
    - serve command creates VoiceAgent with config overrides and calls start()
    - talk command creates VoiceAgent with config overrides and calls talk_interactive()
    - Both commands handle KeyboardInterrupt for graceful shutdown
    - asyncio.run() used for the event loop
    - Logging configured to INFO level on startup
    - --voice default is "boris"
    - --port default is 8765
    - --host default is "0.0.0.0"
    - Exit code 0 on clean shutdown, 1 on error
    - `python -m voiceagent` works via __main__.py
  </constraints>

  <verification>
    - `python -m voiceagent --help` shows usage with "serve" and "talk" subcommands
    - `python -m voiceagent serve --help` shows --voice, --port, --host options
    - `python -m voiceagent talk --help` shows --voice option
    - CLI parses arguments without error
    - pytest tests/voiceagent/test_cli.py passes with 0 failures
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/cli.py:
  """CLI entry point for the voice agent."""
  import asyncio
  import logging
  import sys
  import click
  from voiceagent.config import load_config

  logger = logging.getLogger(__name__)

  @click.group()
  def cli():
      """Voice Agent -- Personal AI Assistant."""
      pass

  @cli.command()
  @click.option("--voice", default="boris", help="ClipCannon voice profile name")
  @click.option("--port", default=8765, type=int, help="WebSocket port")
  @click.option("--host", default="0.0.0.0", help="Bind address")
  def serve(voice, port, host):
      """Start the voice agent server."""
      logging.basicConfig(
          level=logging.INFO,
          format="%(asctime)s %(name)s %(levelname)s %(message)s",
      )
      logger.info("Starting voice agent server (voice=%s, host=%s, port=%d)", voice, host, port)

      config = load_config()
      config.tts.voice_name = voice
      config.transport.port = port
      config.transport.host = host

      from voiceagent.agent import VoiceAgent
      agent = VoiceAgent(config=config)

      async def run():
          try:
              await agent.start()
          except KeyboardInterrupt:
              logger.info("Received interrupt signal")
          finally:
              await agent.shutdown()

      try:
          asyncio.run(run())
      except KeyboardInterrupt:
          pass
      sys.exit(0)

  @cli.command()
  @click.option("--voice", default="boris", help="ClipCannon voice profile name")
  def talk(voice):
      """Interactive voice conversation using local microphone."""
      logging.basicConfig(
          level=logging.INFO,
          format="%(asctime)s %(name)s %(levelname)s %(message)s",
      )
      logger.info("Starting interactive conversation (voice=%s)", voice)

      config = load_config()
      config.tts.voice_name = voice

      from voiceagent.agent import VoiceAgent
      agent = VoiceAgent(config=config)

      async def run():
          try:
              await agent.talk_interactive()
          except KeyboardInterrupt:
              logger.info("Received interrupt signal")
          finally:
              await agent.shutdown()

      try:
          asyncio.run(run())
      except KeyboardInterrupt:
          pass
      sys.exit(0)

  if __name__ == "__main__":
      cli()

src/voiceagent/__main__.py:
  """Allow running as: python -m voiceagent"""
  from voiceagent.cli import cli

  if __name__ == "__main__":
      cli()

tests/voiceagent/test_cli.py:
  """Tests for the CLI entry point using click.testing.CliRunner.
  CliRunner is NOT a mock -- it is click's own test harness for CLI commands."""
  import pytest
  from click.testing import CliRunner
  from voiceagent.cli import cli

  @pytest.fixture
  def runner():
      return CliRunner()

  def test_cli_help(runner):
      """voiceagent --help shows usage with 'serve' and 'talk' subcommands."""
      result = runner.invoke(cli, ["--help"])
      assert result.exit_code == 0
      assert "serve" in result.output
      assert "talk" in result.output
      assert "Voice Agent" in result.output

  def test_serve_help(runner):
      """voiceagent serve --help shows --voice, --port, --host options."""
      result = runner.invoke(cli, ["serve", "--help"])
      assert result.exit_code == 0
      assert "--voice" in result.output
      assert "--port" in result.output
      assert "--host" in result.output
      assert "boris" in result.output  # default value shown

  def test_talk_help(runner):
      """voiceagent talk --help shows --voice option."""
      result = runner.invoke(cli, ["talk", "--help"])
      assert result.exit_code == 0
      assert "--voice" in result.output
      assert "boris" in result.output  # default value shown

  def test_cli_no_args_shows_help(runner):
      """Running voiceagent with no args shows help text."""
      result = runner.invoke(cli, [])
      assert result.exit_code == 0
      assert "serve" in result.output
      assert "talk" in result.output

  def test_serve_default_values(runner):
      """serve command parses default values: voice=boris, port=8765, host=0.0.0.0."""
      # We just verify the help text shows the defaults
      result = runner.invoke(cli, ["serve", "--help"])
      assert "8765" in result.output  # default port
      assert "0.0.0.0" in result.output  # default host
      assert "boris" in result.output  # default voice
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/cli.py">CLI with serve and talk commands using click</file>
  <file path="src/voiceagent/__main__.py">Module entry point for python -m voiceagent</file>
  <file path="tests/voiceagent/test_cli.py">Tests using click.testing.CliRunner</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>CLI group has serve and talk commands</criterion>
  <criterion>serve command accepts --voice, --port, --host options with correct defaults</criterion>
  <criterion>talk command accepts --voice option with default "boris"</criterion>
  <criterion>Help text renders correctly for all commands</criterion>
  <criterion>python -m voiceagent --help works</criterion>
  <criterion>Graceful shutdown on KeyboardInterrupt (exit code 0)</criterion>
  <criterion>All tests pass with 0 failures</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>CLI exit codes and output text</source_of_truth>
  <execute_and_inspect>
    1. Run `python -m voiceagent --help` -- capture stdout
    2. SEPARATELY check exit code is 0
    3. SEPARATELY verify output contains "serve" and "talk" subcommands
    4. Run `python -m voiceagent serve --help` -- capture stdout
    5. SEPARATELY verify output contains --voice, --port, --host with defaults
    6. Run `python -m voiceagent talk --help` -- capture stdout
    7. SEPARATELY verify output contains --voice with default "boris"
  </execute_and_inspect>
  <edge_case_audit>
    <case name="invalid_subcommand">
      <before>User runs: voiceagent invalid_cmd</before>
      <after>Exit code 2 with error message "No such command 'invalid_cmd'"</after>
    </case>
    <case name="invalid_port_type">
      <before>User runs: voiceagent serve --port not_a_number</before>
      <after>Exit code 2 with error message about invalid value for --port</after>
    </case>
    <case name="keyboard_interrupt_during_serve">
      <before>Server is running, user presses Ctrl+C</before>
      <after>Agent shutdown() is called, exit code 0</after>
    </case>
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon
    PYTHONPATH=src python -m pytest tests/voiceagent/test_cli.py -v 2>&amp;1 | grep -E "PASSED|FAILED|ERROR"
    # Expected: all lines show PASSED, 0 FAILED, 0 ERROR

    PYTHONPATH=src python -m voiceagent --help
    # Expected output contains:
    #   Voice Agent -- Personal AI Assistant.
    #   Commands:
    #     serve  Start the voice agent server.
    #     talk   Interactive voice conversation using local microphone.

    PYTHONPATH=src python -m voiceagent serve --help
    # Expected output contains:
    #   --voice TEXT   ClipCannon voice profile name  [default: boris]
    #   --port INTEGER WebSocket port                  [default: 8765]
    #   --host TEXT    Bind address                    [default: 0.0.0.0]

    PYTHONPATH=src python -m voiceagent talk --help
    # Expected output contains:
    #   --voice TEXT   ClipCannon voice profile name  [default: boris]
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="help_output">
    <input>voiceagent --help</input>
    <expected_output>Contains "serve" and "talk" subcommands, exit code 0</expected_output>
  </test>
  <test name="serve_help">
    <input>voiceagent serve --help</input>
    <expected_output>Contains "--voice" (default: boris), "--port" (default: 8765), "--host" (default: 0.0.0.0)</expected_output>
  </test>
  <test name="talk_help">
    <input>voiceagent talk --help</input>
    <expected_output>Contains "--voice" (default: boris), exit code 0</expected_output>
  </test>
  <test name="invalid_command">
    <input>voiceagent bogus</input>
    <expected_output>Exit code 2, error about unknown command</expected_output>
  </test>
</synthetic_test_data>

<manual_verification>
  1. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_cli.py -v
     Verify: all tests PASSED, exit code 0
  2. Run: PYTHONPATH=src python -m voiceagent --help
     Verify: output contains "serve" and "talk", exit code 0
  3. Run: PYTHONPATH=src python -m voiceagent serve --help
     Verify: output contains --voice, --port, --host with correct defaults
  4. Run: PYTHONPATH=src python -m voiceagent talk --help
     Verify: output contains --voice with default "boris"
  5. Run: PYTHONPATH=src python -c "from voiceagent.cli import cli; print('CLI imported OK')"
     Verify: output is "CLI imported OK"
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_cli.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m voiceagent --help</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m voiceagent serve --help</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m voiceagent talk --help</command>
</test_commands>
</task_spec>
```
