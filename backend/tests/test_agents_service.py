from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute, fetch_one
from agflow.schemas.agents import (
    AgentCreate,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentUpdate,
)
from agflow.services import agents_service

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def db() -> AsyncIterator[None]:
    for t in [
        "agent_skills",
        "agent_mcp_servers",
        "agents",
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    # Seed minimal fixtures for FK references
    await execute(
        "INSERT INTO dockerfiles (id, display_name) VALUES ('claude-code', 'Claude Code')"
    )
    await execute(
        "INSERT INTO roles (id, display_name) VALUES ('senior-dev', 'Senior Dev')"
    )
    await execute(
        """
        INSERT INTO discovery_services (id, name, base_url)
        VALUES ('yoops', 'yoops.org', 'https://mcp.yoops.org/api/v1')
        """
    )
    yield
    await close_pool()


async def _seed_mcp(package_id: str = "@mcp/fs") -> str:
    row = await fetch_one(
        """
        INSERT INTO mcp_servers
            (discovery_service_id, package_id, name, repo, repo_url,
             transport, short_description, long_description,
             documentation_url, parameters, parameters_schema)
        VALUES ('yoops', $1, $2, 'modelcontextprotocol/servers',
                'https://github.com/modelcontextprotocol/servers',
                'stdio', '', '', '',
                '{"root": "/data"}'::jsonb, '[]'::jsonb)
        RETURNING id
        """,
        package_id,
        f"MCP {package_id}",
    )
    assert row is not None
    return str(row["id"])


async def _seed_skill(skill_id: str = "markdown") -> str:
    row = await fetch_one(
        """
        INSERT INTO skills
            (discovery_service_id, skill_id, name, description, content_md)
        VALUES ('yoops', $1, $2, '', '# SKILL')
        RETURNING id
        """,
        skill_id,
        f"Skill {skill_id}",
    )
    assert row is not None
    return str(row["id"])


@pytest.mark.asyncio
async def test_create_agent_minimal(db: None) -> None:
    agent = await agents_service.create(
        AgentCreate(
            slug="my-agent",
            display_name="My Agent",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    assert agent.slug == "my-agent"
    assert agent.display_name == "My Agent"
    assert agent.timeout_seconds == 3600
    assert agent.network_mode == "bridge"
    assert agent.mcp_bindings == []
    assert agent.skill_bindings == []
    assert agent.image_status == "missing"  # no build yet


@pytest.mark.asyncio
async def test_create_agent_with_bindings(db: None) -> None:
    mcp_id = await _seed_mcp()
    skill_id = await _seed_skill()
    agent = await agents_service.create(
        AgentCreate(
            slug="full-agent",
            display_name="Full",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[
                AgentMCPBinding(
                    mcp_server_id=mcp_id,  # type: ignore[arg-type]
                    parameters_override={"root": "/workspace"},
                    position=0,
                )
            ],
            skill_bindings=[
                AgentSkillBinding(skill_id=skill_id, position=0)  # type: ignore[arg-type]
            ],
        )
    )
    assert len(agent.mcp_bindings) == 1
    assert agent.mcp_bindings[0].parameters_override == {"root": "/workspace"}
    assert len(agent.skill_bindings) == 1


@pytest.mark.asyncio
async def test_create_duplicate_slug(db: None) -> None:
    payload = AgentCreate(
        slug="dup",
        display_name="Dup",
        dockerfile_id="claude-code",
        role_id="senior-dev",
    )
    await agents_service.create(payload)
    with pytest.raises(agents_service.DuplicateAgentError):
        await agents_service.create(payload)


@pytest.mark.asyncio
async def test_create_invalid_dockerfile(db: None) -> None:
    with pytest.raises(agents_service.InvalidReferenceError):
        await agents_service.create(
            AgentCreate(
                slug="bad",
                display_name="Bad",
                dockerfile_id="does-not-exist",
                role_id="senior-dev",
            )
        )


@pytest.mark.asyncio
async def test_create_invalid_role(db: None) -> None:
    with pytest.raises(agents_service.InvalidReferenceError):
        await agents_service.create(
            AgentCreate(
                slug="bad",
                display_name="Bad",
                dockerfile_id="claude-code",
                role_id="unknown-role",
            )
        )


@pytest.mark.asyncio
async def test_list_all_sorted(db: None) -> None:
    for name in ["Zeta", "Alpha", "Mike"]:
        await agents_service.create(
            AgentCreate(
                slug=name.lower(),
                display_name=name,
                dockerfile_id="claude-code",
                role_id="senior-dev",
            )
        )
    rows = await agents_service.list_all()
    assert [r.display_name for r in rows] == ["Alpha", "Mike", "Zeta"]


@pytest.mark.asyncio
async def test_get_not_found(db: None) -> None:
    from uuid import uuid4

    with pytest.raises(agents_service.AgentNotFoundError):
        await agents_service.get_by_id(uuid4())


@pytest.mark.asyncio
async def test_update_replaces_bindings(db: None) -> None:
    mcp1 = await _seed_mcp("@mcp/a")
    mcp2 = await _seed_mcp("@mcp/b")
    created = await agents_service.create(
        AgentCreate(
            slug="upd",
            display_name="Upd",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[AgentMCPBinding(mcp_server_id=mcp1)],  # type: ignore[arg-type]
        )
    )
    updated = await agents_service.update(
        created.id,
        AgentUpdate(
            display_name="Updated",
            description="new",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[AgentMCPBinding(mcp_server_id=mcp2)],  # type: ignore[arg-type]
            timeout_seconds=7200,
        ),
    )
    assert updated.display_name == "Updated"
    assert updated.timeout_seconds == 7200
    assert len(updated.mcp_bindings) == 1
    assert str(updated.mcp_bindings[0].mcp_server_id) == mcp2


@pytest.mark.asyncio
async def test_delete_cascades_bindings(db: None) -> None:
    mcp = await _seed_mcp()
    skill = await _seed_skill()
    created = await agents_service.create(
        AgentCreate(
            slug="del",
            display_name="Del",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[AgentMCPBinding(mcp_server_id=mcp)],  # type: ignore[arg-type]
            skill_bindings=[AgentSkillBinding(skill_id=skill)],  # type: ignore[arg-type]
        )
    )
    await agents_service.delete(created.id)
    with pytest.raises(agents_service.AgentNotFoundError):
        await agents_service.get_by_id(created.id)
    # Cascades ok
    row = await fetch_one(
        "SELECT COUNT(*) AS c FROM agent_mcp_servers WHERE agent_id = $1",
        created.id,
    )
    assert row is not None and row["c"] == 0


@pytest.mark.asyncio
async def test_duplicate_clones_bindings(db: None) -> None:
    mcp = await _seed_mcp()
    skill = await _seed_skill()
    created = await agents_service.create(
        AgentCreate(
            slug="orig",
            display_name="Original",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[
                AgentMCPBinding(mcp_server_id=mcp, parameters_override={"k": "v"})  # type: ignore[arg-type]
            ],
            skill_bindings=[AgentSkillBinding(skill_id=skill)],  # type: ignore[arg-type]
            timeout_seconds=1234,
        )
    )
    clone = await agents_service.duplicate(
        created.id, new_slug="clone", new_display_name="Clone"
    )
    assert clone.id != created.id
    assert clone.slug == "clone"
    assert clone.display_name == "Clone"
    assert clone.timeout_seconds == 1234
    assert len(clone.mcp_bindings) == 1
    assert clone.mcp_bindings[0].parameters_override == {"k": "v"}
    assert len(clone.skill_bindings) == 1
