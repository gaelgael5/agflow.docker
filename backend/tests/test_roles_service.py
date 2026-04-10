from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import roles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_get_role() -> None:
    summary = await roles_service.create(
        role_id="analyst",
        display_name="Analyst",
        description="Extracts requirements",
        service_types=["specs", "code"],
        identity_md="Tu es un analyste.",
    )

    assert summary.id == "analyst"
    assert summary.display_name == "Analyst"
    assert summary.service_types == ["specs", "code"]
    assert summary.identity_md == "Tu es un analyste."
    assert summary.prompt_agent_md == ""

    again = await roles_service.get_by_id("analyst")
    assert again.display_name == "Analyst"


@pytest.mark.asyncio
async def test_create_rejects_duplicate_id() -> None:
    await roles_service.create(role_id="dup", display_name="A")
    with pytest.raises(roles_service.DuplicateRoleError):
        await roles_service.create(role_id="dup", display_name="B")


@pytest.mark.asyncio
async def test_list_roles_sorted_by_display_name() -> None:
    await roles_service.create(role_id="b_role", display_name="Beta")
    await roles_service.create(role_id="a_role", display_name="Alpha")

    roles = await roles_service.list_all()
    names = [r.display_name for r in roles]
    assert names == ["Alpha", "Beta"]


@pytest.mark.asyncio
async def test_update_role_partial() -> None:
    await roles_service.create(
        role_id="upd", display_name="Old", description="old desc"
    )

    updated = await roles_service.update(
        "upd", display_name="New", description="new desc"
    )
    assert updated.display_name == "New"
    assert updated.description == "new desc"


@pytest.mark.asyncio
async def test_delete_role() -> None:
    await roles_service.create(role_id="to_del", display_name="ToDelete")

    await roles_service.delete("to_del")

    with pytest.raises(roles_service.RoleNotFoundError):
        await roles_service.get_by_id("to_del")


@pytest.mark.asyncio
async def test_get_missing_raises() -> None:
    with pytest.raises(roles_service.RoleNotFoundError):
        await roles_service.get_by_id("does-not-exist")


@pytest.mark.asyncio
async def test_update_prompts() -> None:
    await roles_service.create(role_id="p", display_name="P")

    updated = await roles_service.update_prompts(
        "p",
        prompt_agent_md="Tu es un assistant.",
        prompt_orchestrator_md="Il est un assistant.",
    )
    assert updated.prompt_agent_md == "Tu es un assistant."
    assert updated.prompt_orchestrator_md == "Il est un assistant."
