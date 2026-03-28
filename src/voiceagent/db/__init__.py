"""Voice Agent database module."""
from voiceagent.db.connection import get_connection
from voiceagent.db.schema import init_db

__all__ = ["get_connection", "init_db"]
