from __future__ import annotations

import asyncio as _asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from agflow.api.admin.agents import router as admin_agents_router
from agflow.api.admin.api_keys import router as admin_api_keys_router
from agflow.api.admin.auth import router as admin_auth_router
from agflow.api.admin.containers import router as admin_containers_router
from agflow.api.admin.contracts import router as admin_contracts_router
from agflow.api.admin.discovery_services import router as admin_discovery_router
from agflow.api.admin.dockerfiles import router as admin_dockerfiles_router
from agflow.api.admin.mcp_catalog import router as admin_mcp_catalog_router
from agflow.api.admin.roles import router as admin_roles_router
from agflow.api.admin.secrets import router as admin_secrets_router
from agflow.api.admin.service_types import router as admin_service_types_router
from agflow.api.admin.skills_catalog import router as admin_skills_catalog_router
from agflow.api.admin.templates import router as admin_templates_router
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
from agflow.api.public.messages import router as public_messages_router
from agflow.api.public.params import router as public_params_router
from agflow.api.public.roles import router as public_roles_router
from agflow.api.public.scopes import router as public_scopes_router
from agflow.api.public.sessions import router as public_sessions_router
from agflow.config import get_settings
from agflow.logging_setup import configure_logging
from agflow.workers.session_expiry import run_expiry_loop as _run_expiry_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)
    log.info("app.startup", environment=settings.environment)
    from pathlib import Path

    from agflow.db.migrations import run_migrations
    from agflow.services import (
        agent_files_service,
        dockerfile_files_service,
        dockerfiles_service,
        role_files_service,
        users_service,
    )

    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    # Migrate content to disk BEFORE SQL migrations drop the columns
    await role_files_service.migrate_db_to_disk()
    await agent_files_service.migrate_db_to_disk()
    await dockerfile_files_service.migrate_db_to_disk()
    await run_migrations(migrations_dir)
    await users_service.seed_admin(settings.admin_email)
    for df in await dockerfiles_service.list_all():
        await dockerfile_files_service.seed_standard_files(df.id)
    from agflow.services import agents_catalog_service
    try:
        await agents_catalog_service.sync_from_filesystem()
    except Exception as exc:
        log.warning("agents_catalog.sync.failed", error=str(exc))
    _expiry_stop = _asyncio.Event()
    _expiry_task = _asyncio.create_task(_run_expiry_loop(_expiry_stop))
    yield
    log.info("app.shutdown")
    _expiry_stop.set()
    try:
        await _asyncio.wait_for(_expiry_task, timeout=5)
    except TimeoutError:
        _expiry_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title="agflow.docker",
        version="0.1.0",
        lifespan=lifespan,
        servers=[
            {"url": "https://docker-agflow.yoops.org", "description": "Production"},
        ],
        openapi_tags=[
            {"name": "health", "description": "Health check and readiness probes."},
            {"name": "admin-auth", "description": "Admin authentication — login with email/password or Google OAuth, retrieve current user info."},
            {"name": "admin-users", "description": "User management — list, create, approve, disable, and delete platform users."},
            {"name": "admin-api-keys", "description": "API key management — create, list, revoke keys with scoped permissions and rate limits."},
            {"name": "admin-secrets", "description": "Secrets & environment variables — encrypted storage for API keys, tokens, and credentials used by agents."},
            {"name": "admin-service-types", "description": "Service type categories — classify agent roles (Documentation, Code, Design, etc.)."},
            {"name": "admin-dockerfiles", "description": "Dockerfile management — CRUD for Docker images, file editing, builds, and container configuration."},
            {"name": "admin-templates", "description": "Jinja2 templates — multilingual generation templates for agent prompt and mission files."},
            {"name": "admin-roles", "description": "Role management — composable agent personalities with identity, sections (roles/missions/competences), and documents."},
            {"name": "admin-agents", "description": "Agent composition — assemble Dockerfile + Role + MCP + Skills into a deployable agent with mission profiles."},
            {"name": "admin-contracts", "description": "OpenAPI contracts — attach REST API specs to agents, parsed by tag to generate curl documentation."},
            {"name": "admin-containers", "description": "Container runtime — launch, stop, inspect, and stream tasks to Docker containers."},
            {"name": "admin-discovery", "description": "Discovery services — configure external MCP/Skills registries, test connectivity, fetch targets."},
            {"name": "admin-mcp-catalog", "description": "MCP catalog — install, configure, and manage MCP servers from discovery registries."},
            {"name": "admin-skills-catalog", "description": "Skills catalog — install and manage skill packs from discovery registries."},
            {"name": "admin-vault", "description": "User vault — client-side encrypted secret storage with passphrase-based key derivation."},
            {"name": "admin-user-secrets", "description": "User secrets — per-user encrypted credentials stored in the vault."},
            {"name": "public-sessions", "description": "Public API — session lifecycle (create, extend, close, expire)."},
            {"name": "public-agents", "description": "Public API — agent instance management within sessions."},
            {"name": "public-messages", "description": "Public API — message exchange and WebSocket streaming."},
        ],
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
    app.include_router(admin_contracts_router)
    app.include_router(admin_templates_router)
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
    app.include_router(public_messages_router)
    app.include_router(public_sessions_router)
    app.include_router(public_roles_router)
    return app


app = create_app()
