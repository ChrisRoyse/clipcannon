"""Dashboard route modules for ClipCannon.

Provides API routes for home, credits, projects, provenance,
timeline, editing, and review.
"""

from clipcannon.dashboard.routes.credits import router as credits_router
from clipcannon.dashboard.routes.editing import router as editing_router
from clipcannon.dashboard.routes.home import router as home_router
from clipcannon.dashboard.routes.projects import router as projects_router
from clipcannon.dashboard.routes.provenance import router as provenance_router
from clipcannon.dashboard.routes.review import router as review_router
from clipcannon.dashboard.routes.timeline import router as timeline_router

__all__ = [
    "credits_router",
    "editing_router",
    "home_router",
    "projects_router",
    "provenance_router",
    "review_router",
    "timeline_router",
]
