from __future__ import annotations

import uuid

import pytest

from agflow.db.pool import close_pool, fetch_all
from agflow.schemas.agents import (
    AgentCreate,
    AgentGeneration,
    AgentGenerationProfile,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentUpdate,
)
from agflow.services import agents_service
from agflow.services.agents_service import AgentNotFoundError, DuplicateAgentError
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_migration_creates_agents_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agents' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "slug" in columns
    assert "id" in columns
    assert "mcp_bindings" in columns
    assert "generations" in columns
    assert "is_assistant" in columns


@pytest.mark.asyncio
async def test_migration_creates_agent_profiles_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agent_profiles' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "id" in columns
    assert "agent_slug" in columns
    assert "document_ids" in columns


def _make_create(slug: str = "my-agent", display_name: str = "My Agent") -> AgentCreate:
    return AgentCreate(
        slug=slug,
        display_name=display_name,
        description="desc",
        dockerfile_id="dockerfile-abc",
    )


@pytest.mark.asyncio
async def test_list_all_empty() -> None:
    assert await agents_service.list_all() == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    detail = await agents_service.create(_make_create())
    assert detail.slug == "my-agent"
    assert detail.display_name == "My Agent"
    assert detail.is_assistant is False
    summaries = await agents_service.list_all()
    assert len(summaries) == 1
    assert summaries[0].slug == "my-agent"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    await agents_service.create(_make_create())
    with pytest.raises(DuplicateAgentError):
        await agents_service.create(_make_create())


@pytest.mark.asyncio
async def test_get_by_id() -> None:
    detail = await agents_service.create(_make_create())
    fetched = await agents_service.get_by_id(detail.id)
    assert fetched.slug == "my-agent"


@pytest.mark.asyncio
async def test_get_by_id_not_found_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        await agents_service.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update() -> None:
    detail = await agents_service.create(_make_create())
    updated = await agents_service.update(
        detail.id,
        AgentUpdate(display_name="Renamed", dockerfile_id="dockerfile-abc"),
    )
    assert updated.display_name == "Renamed"
    assert updated.slug == "my-agent"


@pytest.mark.asyncio
async def test_delete() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.delete(detail.id)
    assert await agents_service.list_all() == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        await agents_service.delete(uuid.uuid4())


@pytest.mark.asyncio
async def test_duplicate() -> None:
    detail = await agents_service.create(_make_create("original", "Original"))
    dup = await agents_service.duplicate(detail.id, "copy", "Copy")
    assert dup.slug == "copy"
    assert dup.display_name == "Copy"
    assert len(await agents_service.list_all()) == 2


@pytest.mark.asyncio
async def test_get_assistant_returns_none_when_none() -> None:
    await agents_service.create(_make_create())
    assert await agents_service.get_assistant() is None


@pytest.mark.asyncio
async def test_set_assistant() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.set_assistant(detail.id)
    assistant = await agents_service.get_assistant()
    assert assistant is not None
    assert assistant.slug == "my-agent"
    assert assistant.is_assistant is True


@pytest.mark.asyncio
async def test_set_assistant_clears_previous() -> None:
    a = await agents_service.create(_make_create("agent-a", "A"))
    b = await agents_service.create(_make_create("agent-b", "B"))
    await agents_service.set_assistant(a.id)
    await agents_service.set_assistant(b.id)
    assistant = await agents_service.get_assistant()
    assert assistant is not None and assistant.slug == "agent-b"
    a_refetched = await agents_service.get_by_id(a.id)
    assert a_refetched.is_assistant is False


@pytest.mark.asyncio
async def test_clear_assistant() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.set_assistant(detail.id)
    await agents_service.clear_assistant()
    assert await agents_service.get_assistant() is None


@pytest.mark.asyncio
async def test_mcp_bindings_stored_and_retrieved() -> None:
    mcp_id = uuid.uuid4()
    payload = AgentCreate(
        slug="agent-mcp",
        display_name="MCP Agent",
        dockerfile_id="df",
        mcp_bindings=[AgentMCPBinding(mcp_server_id=mcp_id, parameters_override={"key": "val"}, position=1)],
    )
    detail = await agents_service.create(payload)
    assert len(detail.mcp_bindings) == 1
    assert detail.mcp_bindings[0].mcp_server_id == mcp_id
    assert detail.mcp_bindings[0].parameters_override == {"key": "val"}


@pytest.mark.asyncio
async def test_skill_bindings_stored_and_retrieved() -> None:
    skill_id = uuid.uuid4()
    payload = AgentCreate(
        slug="agent-skill",
        display_name="Skill Agent",
        dockerfile_id="df",
        skill_bindings=[AgentSkillBinding(skill_id=skill_id)],
    )
    detail = await agents_service.create(payload)
    assert len(detail.skill_bindings) == 1
    assert detail.skill_bindings[0].skill_id == skill_id


@pytest.mark.asyncio
async def test_generations_stored_and_retrieved() -> None:
    gen = AgentGeneration(
        role_id="assistant",
        template_slug="base",
        template_culture="fr",
        prompt_filename="prompt.md",
        profiles=[AgentGenerationProfile(name="p1", documents=["roles/doc.md"])],
    )
    payload = AgentCreate(
        slug="agent-gen",
        display_name="Gen Agent",
        dockerfile_id="df",
        generations=[gen],
    )
    detail = await agents_service.create(payload)
    assert len(detail.generations) == 1
    assert detail.generations[0].role_id == "assistant"
    assert detail.generations[0].profiles[0].name == "p1"


@pytest.mark.asyncio
async def test_env_overrides_stored_and_retrieved() -> None:
    payload = AgentCreate(
        slug="agent-env",
        display_name="Env Agent",
        dockerfile_id="df",
        env_vars={"env_overrides": {"MY_VAR": "hello"}, "mount_overrides": {}, "param_overrides": {}},
    )
    detail = await agents_service.create(payload)
    assert detail.env_vars["env_overrides"]["MY_VAR"] == "hello"


@pytest.mark.asyncio
async def test_skill_binding_position_preserved() -> None:
    skill_id = uuid.uuid4()
    payload = AgentCreate(
        slug="agent-skill-pos",
        display_name="Skill Pos",
        dockerfile_id="df",
        skill_bindings=[AgentSkillBinding(skill_id=skill_id, position=3)],
    )
    detail = await agents_service.create(payload)
    assert detail.skill_bindings[0].position == 3


@pytest.mark.asyncio
async def test_set_assistant_not_found_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        await agents_service.set_assistant(uuid.uuid4())
