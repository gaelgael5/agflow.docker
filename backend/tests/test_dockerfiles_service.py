from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")


from agflow.services import dockerfiles_service
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield


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
