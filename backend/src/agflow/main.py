from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agflow.api.admin.agents import router as admin_agents_router
from agflow.api.admin.auth import router as admin_auth_router
from agflow.api.admin.discovery_services import router as admin_discovery_router
from agflow.api.admin.dockerfiles import router as admin_dockerfiles_router
from agflow.api.admin.mcp_catalog import router as admin_mcp_catalog_router
from agflow.api.admin.roles import router as admin_roles_router
from agflow.api.admin.secrets import router as admin_secrets_router
from agflow.api.admin.service_types import router as admin_service_types_router
from agflow.api.admin.skills_catalog import router as admin_skills_catalog_router
from agflow.api.health import router as health_router
from agflow.config import get_settings
from agflow.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("app.startup", environment=settings.environment)
    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="agflow.docker",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(admin_auth_router)
    app.include_router(admin_secrets_router)
    app.include_router(admin_service_types_router)
    app.include_router(admin_roles_router)
    app.include_router(admin_dockerfiles_router)
    app.include_router(admin_discovery_router)
    app.include_router(admin_mcp_catalog_router)
    app.include_router(admin_skills_catalog_router)
    app.include_router(admin_agents_router)
    return app


app = create_app()
