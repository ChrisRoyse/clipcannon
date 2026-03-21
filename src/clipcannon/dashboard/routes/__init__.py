"""Dashboard route modules for ClipCannon.

Provides API routes for home, credits, projects, and provenance.
"""

from clipcannon.dashboard.routes.credits import router as credits_router
from clipcannon.dashboard.routes.home import router as home_router
from clipcannon.dashboard.routes.projects import router as projects_router
from clipcannon.dashboard.routes.provenance import router as provenance_router

__all__ = [
    "credits_router",
    "home_router",
    "projects_router",
    "provenance_router",
]
