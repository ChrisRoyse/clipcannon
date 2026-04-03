"""CLI entry point for the voice agent."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from types import FrameType

from voiceagent import __version__


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """Voice Agent -- Personal AI Assistant."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


@cli.command()
@click.option("--voice", default="boris", show_default=True, help="ClipCannon voice profile name")
@click.option("--port", default=8765, type=int, show_default=True, help="WebSocket port")
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind address")
def serve(voice: str, port: int, host: str) -> None:
    """Start the voice agent server."""
    from voiceagent.agent import VoiceAgent
    from voiceagent.config import TransportConfig, TTSConfig, VoiceAgentConfig

    config = VoiceAgentConfig(
        transport=TransportConfig(host=host, port=port),
        tts=TTSConfig(voice_name=voice),
    )
    agent = VoiceAgent(config=config)

    def _shutdown(signum: int, frame: FrameType | None) -> None:
        click.echo("Shutting down...")
        agent.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        agent.start()
    except KeyboardInterrupt:
        agent.shutdown()


@cli.command()
@click.option("--voice", default="boris", show_default=True, help="ClipCannon voice profile name")
def talk(voice: str) -> None:
    """Interactive voice conversation (Pipecat + Ollama, recommended)."""
    from voiceagent.pipecat_agent import run_agent

    try:
        asyncio.run(run_agent(voice_name=voice))
    except KeyboardInterrupt:
        click.echo("Shutting down...")


@cli.command()
@click.option("--voice", default="boris", show_default=True, help="Default voice profile")
@click.option("--threshold", default=0.72, show_default=True, help="Wake phrase similarity threshold")
def listen(voice: str, threshold: float) -> None:
    """Always-on wake word listener. Say 'Hey Jarvis' to activate."""
    from voiceagent.wake_listener import WakeWordListener

    listener = WakeWordListener(voice_name=voice, threshold=threshold)
    try:
        listener.run()
    except KeyboardInterrupt:
        click.echo("Shutting down...")


@cli.command(name="talk-legacy")
@click.option("--voice", default="boris", show_default=True, help="ClipCannon voice profile name")
def talk_legacy(voice: str) -> None:
    """Interactive voice conversation (legacy custom pipeline)."""
    from voiceagent.agent import VoiceAgent
    from voiceagent.config import TTSConfig, VoiceAgentConfig

    config = VoiceAgentConfig(tts=TTSConfig(voice_name=voice))
    agent = VoiceAgent(config=config)

    try:
        asyncio.run(agent.talk_interactive())
    except KeyboardInterrupt:
        click.echo("Interrupted")
    finally:
        agent.shutdown()


# ------------------------------------------------------------------
# Meeting clone commands
# ------------------------------------------------------------------


@cli.group()
def meeting() -> None:
    """Clone Meeting Agent -- attend meetings as your AI clone."""


@meeting.command()
@click.option("--clone", required=True, help="Clone name (must match a voice profile)")
@click.option("--voice", default=None, help="Override voice profile name")
@click.option("--driver", default=None, type=click.Path(exists=True), help="Driver video path for avatar")
@click.option("--platform", default="unknown", show_default=True, help="Meeting platform (zoom, google_meet, teams)")
def start(clone: str, voice: str | None, driver: str | None, platform: str) -> None:
    """Start a clone in Mode 1 (virtual device -- replace me)."""
    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        instance = await mgr.start_clone(
            clone_name=clone,
            voice_profile=voice,
            driver_video=driver,
            platform=platform,
        )
        click.echo(
            f"Clone '{clone}' started (meeting={instance.meeting_id}, "
            f"platform={platform})"
        )
        click.echo("Press Ctrl+C to stop...")

        stop_event = asyncio.Event()

        def _on_signal() -> None:
            stop_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal)

        await stop_event.wait()

        click.echo(f"Stopping clone '{clone}'...")
        doc_id = await mgr.stop_clone(clone)
        if doc_id:
            click.echo(f"Transcript ingested: doc_id={doc_id}")
        else:
            click.echo("Transcript ingest failed or no segments recorded.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo("Shutting down...")


@meeting.command()
@click.option("--clone", required=True, help="Clone name to stop")
def stop(clone: str) -> None:
    """Stop a running clone."""
    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        doc_id = await mgr.stop_clone(clone)
        if doc_id:
            click.echo(f"Clone '{clone}' stopped. doc_id={doc_id}")
        else:
            click.echo(f"Clone '{clone}' was not running or stop failed.")

    asyncio.run(_run())


@meeting.command(name="stop-all")
def stop_all() -> None:
    """Stop all running clones."""
    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        await mgr.stop_all()
        click.echo("All clones stopped.")

    asyncio.run(_run())


@meeting.command(name="list")
def list_clones() -> None:
    """List active running clones."""
    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)
    clones = mgr.list_clones()
    if not clones:
        click.echo("No active clones.")
    else:
        click.echo(f"Active clones ({len(clones)}):")
        for name in clones:
            click.echo(f"  - {name}")


@meeting.command()
@click.option("--url", required=True, help="Meeting URL to join")
@click.option("--name", "display_name", default="AI Notes", show_default=True, help="Display name in participant list")
@click.option("--clone", required=True, help="Clone name for responses")
@click.option("--voice", default=None, help="Override voice profile name")
def join(url: str, display_name: str, clone: str, voice: str | None) -> None:
    """Join a meeting as a bot participant (Mode 2 -- placeholder)."""
    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        await mgr.join_meeting(
            meeting_url=url,
            display_name=display_name,
            clone_name=clone,
            voice_profile=voice,
        )

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@meeting.command()
@click.option("--limit", default=50, show_default=True, help="Max meetings to list")
def history(limit: int) -> None:
    """List past meetings from OCR Provenance."""
    import json

    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        result = await mgr.list_meetings(limit=limit)
        click.echo(json.dumps(result, indent=2, default=str))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@meeting.command()
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Max results")
def search(query: str, limit: int) -> None:
    """Search past meetings in OCR Provenance."""
    import json

    from voiceagent.meeting.config import load_meeting_config
    from voiceagent.meeting.manager import CloneMeetingManager

    config = load_meeting_config()
    mgr = CloneMeetingManager(config=config)

    async def _run() -> None:
        result = await mgr.search_meetings(query=query, limit=limit)
        click.echo(json.dumps(result, indent=2, default=str))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@meeting.command(name="setup-devices")
@click.option("--clones", required=True, help="Comma-separated list of clone names")
def setup_devices(clones: str) -> None:
    """Create v4l2loopback + PulseAudio devices for clones."""
    from voiceagent.meeting.devices import CloneDeviceManager

    clone_names = [n.strip() for n in clones.split(",") if n.strip()]
    if not clone_names:
        click.echo("Error: no clone names provided.", err=True)
        sys.exit(1)

    dm = CloneDeviceManager()

    # Check v4l2loopback
    if not dm.check_v4l2loopback():
        click.echo(
            "Warning: v4l2loopback kernel module not loaded. "
            "Video devices will not work until loaded: "
            "sudo modprobe v4l2loopback devices=4",
            err=True,
        )

    for name in clone_names:
        try:
            pair = dm.create_audio_devices(name)
            click.echo(
                f"  {name}: video={pair.video_device}, "
                f"sink={pair.audio_sink}, source={pair.audio_source}"
            )
        except Exception as e:
            click.echo(f"  {name}: FAILED -- {e}", err=True)

    click.echo(f"Device setup complete for {len(clone_names)} clone(s).")
