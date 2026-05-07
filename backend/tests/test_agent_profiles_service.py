from __future__ import annotations

import uuid

import pytest

from agflow.db.pool import close_pool
from agflow.schemas.agents import AgentCreate
from agflow.services import agent_profiles_service, agents_service
from agflow.services.agent_profiles_service import DuplicateProfileError, ProfileNotFoundError
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


async def _make_agent(slug: str = "my-agent") -> uuid.UUID:
    detail = await agents_service.create(
        AgentCreate(slug=slug, display_name="My Agent", dockerfile_id="df")
    )
    return detail.id


@pytest.mark.asyncio
async def test_list_for_agent_empty() -> None:
    agent_id = await _make_agent()
    assert await agent_profiles_service.list_for_agent(agent_id) == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "Profile 1", "desc")
    assert profile.name == "Profile 1"
    assert profile.agent_id == agent_id
    profiles = await agent_profiles_service.list_for_agent(agent_id)
    assert len(profiles) == 1
    assert profiles[0].name == "Profile 1"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    agent_id = await _make_agent()
    await agent_profiles_service.create(agent_id, "Profile 1")
    with pytest.raises(DuplicateProfileError):
        await agent_profiles_service.create(agent_id, "Profile 1")


@pytest.mark.asyncio
async def test_get_by_id() -> None:
    agent_id = await _make_agent()
    created = await agent_profiles_service.create(agent_id, "Profile 1")
    fetched = await agent_profiles_service.get_by_id(created.id)
    assert fetched.name == "Profile 1"


@pytest.mark.asyncio
async def test_get_by_id_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_name_and_description() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "Old Name")
    updated = await agent_profiles_service.update(profile.id, name="New Name", description="updated")
    assert updated.name == "New Name"
    assert updated.description == "updated"


@pytest.mark.asyncio
async def test_update_document_ids() -> None:
    agent_id = await _make_agent()
    doc_id = uuid.uuid4()
    profile = await agent_profiles_service.create(agent_id, "P")
    updated = await agent_profiles_service.update(profile.id, document_ids=[doc_id])
    assert doc_id in updated.document_ids


@pytest.mark.asyncio
async def test_delete() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "P")
    await agent_profiles_service.delete(profile.id)
    assert await agent_profiles_service.list_for_agent(agent_id) == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.delete(uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_agent_cascades_profiles() -> None:
    agent_id = await _make_agent()
    await agent_profiles_service.create(agent_id, "P1")
    await agents_service.delete(agent_id)
    assert await agents_service.list_all() == []


@pytest.mark.asyncio
async def test_create_agent_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.create(uuid.uuid4(), "Profile")


@pytest.mark.asyncio
async def test_update_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.update(uuid.uuid4(), name="X")


@pytest.mark.asyncio
async def test_update_no_op_returns_unchanged() -> None:
    agent_id = await _make_agent("agent-noop")
    profile = await agent_profiles_service.create(agent_id, "Stable")
    result = await agent_profiles_service.update(profile.id)
    assert result.name == "Stable"
