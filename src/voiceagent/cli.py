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
    """Interactive voice conversation using local microphone."""
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
