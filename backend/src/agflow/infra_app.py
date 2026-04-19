"""Infrastructure API — separate FastAPI app on port 8001.

Shares the same database pool and services as the main app.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agflow.api.infra.certificates import router as certificates_router
from agflow.api.infra.platforms import router as platforms_router
from agflow.api.infra.servers import router as servers_router
from agflow.api.infra.services import router as services_router
from agflow.api.infra.types import router as types_router
from agflow.db.pool import close_pool, get_pool
from agflow.logging_setup import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Pool is created lazily by get_pool() on first query
    await get_pool()
    log.info("infra_app.startup", port=8001)

    # Run migrations (shared with main app)
    from pathlib import Path

    from agflow.db.migrations import run_migrations

    migrations_dir = Path(__file__).parent.parent / "migrations"
    await run_migrations(migrations_dir)

    yield

    log.info("infra_app.shutdown")
    await close_pool()


def create_infra_app() -> FastAPI:
    app = FastAPI(
        title="agflow.docker — Infrastructure",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(types_router)
    app.include_router(platforms_router)
    app.include_router(services_router)
    app.include_router(servers_router)
    app.include_router(certificates_router)

    return app


app = create_infra_app()
