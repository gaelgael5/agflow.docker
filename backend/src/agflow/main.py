from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agflow.api.admin.agents import router as admin_agents_router
from agflow.api.admin.api_keys import router as admin_api_keys_router
from agflow.api.admin.auth import router as admin_auth_router
from agflow.api.admin.containers import router as admin_containers_router
from agflow.api.admin.discovery_services import router as admin_discovery_router
from agflow.api.admin.dockerfiles import router as admin_dockerfiles_router
from agflow.api.admin.mcp_catalog import router as admin_mcp_catalog_router
from agflow.api.admin.roles import router as admin_roles_router
from agflow.api.admin.secrets import router as admin_secrets_router
from agflow.api.admin.service_types import router as admin_service_types_router
from agflow.api.admin.skills_catalog import router as admin_skills_catalog_router
from agflow.api.admin.terminal import router as admin_terminal_router
from agflow.api.admin.user_secrets import router as admin_user_secrets_router
from agflow.api.admin.users import router as admin_users_router
from agflow.api.admin.vault import router as admin_vault_router
from agflow.api.health import router as health_router
from agflow.api.public.agents import router as public_agents_router
from agflow.api.public.containers import router as public_containers_router
from agflow.api.public.dockerfiles import router as public_dockerfiles_router
from agflow.api.public.files import router as public_files_router
from agflow.api.public.launched import router as public_launched_router
from agflow.api.public.params import router as public_params_router
from agflow.api.public.roles import router as public_roles_router
from agflow.api.public.scopes import router as public_scopes_router
from agflow.config import get_settings
from agflow.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("app.startup", environment=settings.environment)
    from pathlib import Path

    from agflow.db.migrations import run_migrations
    from agflow.services import dockerfile_files_service, dockerfiles_service, users_service

    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    await run_migrations(migrations_dir)
    await dockerfile_files_service.migrate_db_to_disk()
    await users_service.seed_admin(settings.admin_email)
    for df in await dockerfiles_service.list_all():
        await dockerfile_files_service.seed_standard_files(df.id)
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
    app.include_router(admin_containers_router)
    app.include_router(admin_discovery_router)
    app.include_router(admin_mcp_catalog_router)
    app.include_router(admin_skills_catalog_router)
    app.include_router(admin_agents_router)
    app.include_router(admin_terminal_router)
    app.include_router(admin_users_router)
    app.include_router(admin_api_keys_router)
    app.include_router(admin_vault_router)
    app.include_router(admin_user_secrets_router)
    app.include_router(public_dockerfiles_router)
    app.include_router(public_files_router)
    app.include_router(public_params_router)
    app.include_router(public_launched_router)
    app.include_router(public_scopes_router)
    app.include_router(public_agents_router)
    app.include_router(public_containers_router)
    app.include_router(public_roles_router)
    return app


app = create_app()
