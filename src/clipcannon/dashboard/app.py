"""ClipCannon dashboard web application.

FastAPI application serving the dashboard UI on port 3200. Provides
JSON API endpoints for credits, projects, provenance, and system health,
along with a static HTML frontend.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from clipcannon import __version__
from clipcannon.dashboard.auth import is_dev_mode

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).parent
STATIC_DIR = DASHBOARD_DIR / "static"
DEFAULT_PORT = 3200


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control during the application lifetime.
    """
    logger.info(
        "ClipCannon Dashboard v%s starting on port %d (dev_mode=%s)",
        __version__,
        DEFAULT_PORT,
        is_dev_mode(),
    )
    yield
    logger.info("ClipCannon Dashboard shutting down.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Returns:
        Configured FastAPI application with all routes and middleware.
    """
    app = FastAPI(
        title="ClipCannon Dashboard",
        version=__version__,
        description="ClipCannon video pipeline dashboard and API",
        lifespan=lifespan,
    )

    # CORS middleware for local development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3200",
            "http://127.0.0.1:3200",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unhandled exceptions with a structured JSON response.

        Args:
            request: The incoming request.
            exc: The unhandled exception.

        Returns:
            JSONResponse with error details.
        """
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal server error occurred.",
                },
            },
        )

    # Health endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Dictionary with status and version.
        """
        return {
            "status": "ok",
            "version": __version__,
            "service": "clipcannon-dashboard",
        }

    # Register route modules
    from clipcannon.dashboard.routes.credits import router as credits_router
    from clipcannon.dashboard.routes.home import router as home_router
    from clipcannon.dashboard.routes.projects import router as projects_router
    from clipcannon.dashboard.routes.provenance import router as provenance_router

    app.include_router(home_router)
    app.include_router(credits_router)
    app.include_router(projects_router)
    app.include_router(provenance_router)

    # Register auth routes
    from clipcannon.dashboard.auth import router as auth_router

    app.include_router(auth_router)

    # Mount static files last so API routes take precedence
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def main() -> None:
    """Run the dashboard server with uvicorn.

    Entry point for ``python -m clipcannon.dashboard.app``.
    """
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    port = int(os.environ.get("CLIPCANNON_DASHBOARD_PORT", str(DEFAULT_PORT)))
    logger.info("Starting ClipCannon Dashboard on port %d", port)

    uvicorn.run(
        "clipcannon.dashboard.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        reload=is_dev_mode(),
        log_level="info",
    )


if __name__ == "__main__":
    main()
