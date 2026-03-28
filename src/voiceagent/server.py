"""FastAPI server for the voice agent."""
from __future__ import annotations

import json
import logging
import time

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException

from voiceagent import __version__

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Factory that returns a configured FastAPI instance."""
    app = FastAPI(title="VoiceAgent", version=__version__)
    app.state.start_time = time.monotonic()
    app.state.on_audio = None
    app.state.on_control = None
    app.state.active_ws = None
    app.state.db_conn = None

    @app.get("/health")
    async def health():
        uptime_s = round(time.monotonic() - app.state.start_time, 3)
        return {"status": "ok", "version": __version__, "uptime_s": uptime_s}

    @app.get("/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str):
        if app.state.db_conn is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        cursor = app.state.db_conn.execute(
            "SELECT id, started_at, ended_at, voice_profile, turn_count FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "id": row["id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "voice_profile": row["voice_profile"],
            "turn_count": row["turn_count"],
        }

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        app.state.active_ws = ws
        logger.info("WebSocket client connected")
        try:
            while True:
                message = await ws.receive()
                if "bytes" in message and message["bytes"]:
                    audio = np.frombuffer(message["bytes"], dtype=np.int16)
                    if app.state.on_audio:
                        await app.state.on_audio(audio)
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                        if app.state.on_control:
                            await app.state.on_control(data)
                    except json.JSONDecodeError:
                        logger.error("Malformed JSON on WebSocket")
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.info("WebSocket error: %s", e)
        finally:
            app.state.active_ws = None

    return app
