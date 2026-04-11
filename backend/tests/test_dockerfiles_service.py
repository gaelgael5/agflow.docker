from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import dockerfiles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_get() -> None:
    summary = await dockerfiles_service.create(
        dockerfile_id="claude-code",
        display_name="Claude Code",
        description="CLI agent claude-code",
        parameters={"ANTHROPIC_API_KEY": None},
    )
    assert summary.id == "claude-code"
    assert summary.display_name == "Claude Code"
    assert summary.parameters == {"ANTHROPIC_API_KEY": None}
    assert summary.display_status == "never_built"

    again = await dockerfiles_service.get_by_id("claude-code")
    assert again.id == "claude-code"


@pytest.mark.asyncio
async def test_duplicate_raises() -> None:
    await dockerfiles_service.create(dockerfile_id="dup", display_name="D")
    with pytest.raises(dockerfiles_service.DuplicateDockerfileError):
        await dockerfiles_service.create(dockerfile_id="dup", display_name="D2")


@pytest.mark.asyncio
async def test_list_all() -> None:
    await dockerfiles_service.create(dockerfile_id="b", display_name="B")
    await dockerfiles_service.create(dockerfile_id="a", display_name="A")

    items = await dockerfiles_service.list_all()
    assert [i.id for i in items] == ["a", "b"]


@pytest.mark.asyncio
async def test_update() -> None:
    await dockerfiles_service.create(dockerfile_id="upd", display_name="Old")

    updated = await dockerfiles_service.update(
        "upd", display_name="New", description="desc"
    )
    assert updated.display_name == "New"
    assert updated.description == "desc"


@pytest.mark.asyncio
async def test_delete() -> None:
    await dockerfiles_service.create(dockerfile_id="del", display_name="Del")
    await dockerfiles_service.delete("del")

    with pytest.raises(dockerfiles_service.DockerfileNotFoundError):
        await dockerfiles_service.get_by_id("del")
