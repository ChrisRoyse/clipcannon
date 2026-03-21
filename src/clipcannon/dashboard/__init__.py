"""Dashboard web UI for ClipCannon.

Provides a FastAPI-based web dashboard with JSON API endpoints
for credits, projects, provenance, and system health. Serves a
static HTML frontend on port 3200.
"""

from clipcannon.dashboard.app import create_app

__all__ = ["create_app"]
