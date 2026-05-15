from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.schemas.agents import (
    AgentCreate,
    AgentMCPBinding,
    AgentSkillBinding,
)
from agflow.services import agents_service, composition_builder, roles_service
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def db() -> AsyncIterator[None]:
    from agflow.services import dockerfiles_service

    await reset_schema_and_migrate()
    await dockerfiles_service.create(
        dockerfile_id="claude-code", display_name="Claude Code"
    )
    await roles_service.create(
        role_id="senior-dev",
        display_name="Senior Dev",
        identity_md="Tu es un dev senior.",
    )
    await execute(
        """
        INSERT INTO discovery_services (id, name, base_url)
        VALUES ('yoops', 'yoops.org', 'https://mcp.yoops.org/api/v1')
        """
    )
    yield


async def _seed_mcp(name: str = "Filesystem") -> str:
    row = await fetch_one(
        """
        INSERT INTO mcp_servers
            (discovery_service_id, package_id, name, repo, repo_url,
             transport, short_description, long_description,
             documentation_url, parameters, parameters_schema)
        VALUES ('yoops', $1, $2, 'modelcontextprotocol/servers',
                'https://github.com/mcp/fs', 'stdio',
                'FS access', '', '',
                '{"root": "/data", "readonly": false}'::jsonb, '[]'::jsonb)
        RETURNING id
        """,
        f"@mcp/{name.lower()}",
        name,
    )
    assert row is not None
    return str(row["id"])


async def _seed_skill(name: str = "Markdown") -> str:
    row = await fetch_one(
        """
        INSERT INTO skills
            (discovery_service_id, skill_id, name, description, content_md)
        VALUES ('yoops', $1, $2, 'md skill', '# Markdown skill\n\nGuidelines.')
        RETURNING id
        """,
        name.lower(),
        name,
    )
    assert row is not None
    return str(row["id"])


@pytest.mark.asyncio
async def test_preview_minimal_agent(db: None) -> None:
    agent = await agents_service.create(
        AgentCreate(
            slug="min",
            display_name="Min",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    assert "# Identité" in preview.prompt_md
    assert "Tu es un dev senior" in preview.prompt_md
    assert preview.mcp_json == {"mcpServers": {}}
    assert preview.tools_json == []
    assert preview.env_file == ""
    assert preview.skills == []
    # image_status is "missing" (no build) → validation error present
    assert preview.image_status == "missing"
    assert any("image" in e.lower() for e in preview.validation_errors)


@pytest.mark.asyncio
async def test_preview_merges_mcp_params_with_override(db: None) -> None:
    mcp_id = await _seed_mcp()
    agent = await agents_service.create(
        AgentCreate(
            slug="ov",
            display_name="Ov",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            mcp_bindings=[
                AgentMCPBinding(
                    mcp_server_id=mcp_id,  # type: ignore[arg-type]
                    parameters_override={"root": "/workspace/project"},
                )
            ],
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    assert "Filesystem" in preview.mcp_json["mcpServers"]
    merged = preview.mcp_json["mcpServers"]["Filesystem"]["parameters"]
    # override wins for root, original readonly is kept
    assert merged == {"root": "/workspace/project", "readonly": False}
    assert preview.mcp_json["mcpServers"]["Filesystem"]["transport"] == "stdio"
    assert any(t["source"] == "Filesystem" for t in preview.tools_json)


@pytest.mark.asyncio
async def test_preview_includes_skills(db: None) -> None:
    skill_id = await _seed_skill("Markdown")
    agent = await agents_service.create(
        AgentCreate(
            slug="sk",
            display_name="Sk",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            skill_bindings=[AgentSkillBinding(skill_id=skill_id)],  # type: ignore[arg-type]
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    assert len(preview.skills) == 1
    assert preview.skills[0].name == "Markdown"
    assert "Guidelines" in preview.skills[0].content_md


@pytest.mark.asyncio
async def test_preview_resolves_env_vars_from_secrets(db: None, vault_mock) -> None:
    # Le secret est posé dans le vault mocké ; le composition_builder le résout
    # via secrets_service.resolve_env qui passe par vault_client.
    from agflow.services import secrets_service

    await secrets_service.create("OPENAI_API_KEY", "sk-test-123")
    agent = await agents_service.create(
        AgentCreate(
            slug="env",
            display_name="Env",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            env_vars={
                "env_overrides": {
                    "OPENAI_API_KEY": "$OPENAI_API_KEY",
                    "LITERAL": "hello",
                }
            },
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    lines = preview.env_file.splitlines()
    assert "OPENAI_API_KEY=sk-test-123" in lines
    assert "LITERAL=hello" in lines
    assert not any("secret" in e.lower() for e in preview.validation_errors)


@pytest.mark.asyncio
async def test_preview_reports_missing_secret(db: None, vault_mock) -> None:
    agent = await agents_service.create(
        AgentCreate(
            slug="miss",
            display_name="Miss",
            dockerfile_id="claude-code",
            role_id="senior-dev",
            env_vars={"env_overrides": {"MISSING_KEY": "$MISSING_KEY"}},
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    assert "MISSING_KEY=<missing>" in preview.env_file
    assert any("MISSING_KEY" in e for e in preview.validation_errors)


@pytest.mark.asyncio
async def test_preview_reports_stale_image(db: None) -> None:
    # dockerfile_files est filesystem-based : on passe par le service pour
    # déposer un contenu, et seul dockerfile_builds reste en DB.
    from agflow.services import dockerfile_files_service

    files = await dockerfile_files_service.list_for_dockerfile("claude-code")
    dockerfile_file = next(f for f in files if f.path == "Dockerfile")
    await dockerfile_files_service.update(dockerfile_file.id, content="FROM python:3.12")
    await execute(
        """
        INSERT INTO dockerfile_builds
            (dockerfile_id, content_hash, image_tag, status, finished_at)
        VALUES ('claude-code', 'old-hash', 'agflow-claude-code:old-hash',
                'success', NOW())
        """
    )
    agent = await agents_service.create(
        AgentCreate(
            slug="stale",
            display_name="Stale",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    preview = await composition_builder.build_preview(agent.id)
    assert preview.image_status == "stale"
    assert any("stale" in e.lower() for e in preview.validation_errors)


# ─────────────────────────────────────────────────────────────────────────
# NF-3 — Mission profiles
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_default_is_identity_only(db: None) -> None:
    """Without a profile, the prompt must contain only the role identity,
    never the role's documents (even if they exist)."""
    from agflow.services import role_documents_service

    # Seed role documents — they should NOT appear in the default preview.
    await role_documents_service.create(
        role_id="senior-dev",
        section="roles",
        name="analyst",
        content_md="Tu analyses le code source.",
    )
    await role_documents_service.create(
        role_id="senior-dev",
        section="missions",
        name="refactor",
        content_md="Tu refactorises sans casser les tests.",
    )

    agent = await agents_service.create(
        AgentCreate(
            slug="id-only",
            display_name="Id Only",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    preview = await composition_builder.build_preview(agent.id)

    assert "Tu es un dev senior" in preview.prompt_md
    # Role documents must NOT leak into the default prompt
    assert "Tu analyses le code" not in preview.prompt_md
    assert "Tu refactorises" not in preview.prompt_md
    assert preview.profile_name is None
    assert preview.broken_document_ids == []


@pytest.mark.asyncio
async def test_preview_with_profile_includes_selected_docs(db: None) -> None:
    from agflow.services import agent_profiles_service, role_documents_service

    doc1 = await role_documents_service.create(
        role_id="senior-dev",
        section="roles",
        name="analyst",
        content_md="Tu analyses le code source.",
    )
    doc2 = await role_documents_service.create(
        role_id="senior-dev",
        section="missions",
        name="refactor",
        content_md="Tu refactorises sans casser les tests.",
    )
    await role_documents_service.create(
        role_id="senior-dev",
        section="competences",
        name="unused",
        content_md="Tu utilises aussi awk mais on ne veut pas ça ici.",
    )

    agent = await agents_service.create(
        AgentCreate(
            slug="with-profile",
            display_name="With Profile",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    profile = await agent_profiles_service.create(
        agent_id=agent.id,
        name="refactor-mode",
        description="Dev mode refactor",
        document_ids=[doc1.id, doc2.id],
    )

    preview = await composition_builder.build_preview(agent.id, profile.id)
    assert preview.profile_name == "refactor-mode"
    assert "Tu analyses le code" in preview.prompt_md
    assert "Tu refactorises" in preview.prompt_md
    assert "awk" not in preview.prompt_md  # not referenced by the profile
    assert preview.broken_document_ids == []


@pytest.mark.asyncio
async def test_preview_with_profile_detects_broken_refs(db: None) -> None:
    from uuid import uuid4

    from agflow.services import agent_profiles_service

    agent = await agents_service.create(
        AgentCreate(
            slug="broken",
            display_name="Broken",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    ghost_id = uuid4()
    profile = await agent_profiles_service.create(
        agent_id=agent.id,
        name="dangling",
        document_ids=[ghost_id],
    )

    preview = await composition_builder.build_preview(agent.id, profile.id)
    assert ghost_id in preview.broken_document_ids
    assert any("missing document" in e for e in preview.validation_errors)


@pytest.mark.xfail(
    reason="agents_service.list_all() ne calcule pas has_errors (jamais "
    "implémenté côté service — schéma a le champ avec default False). "
    "Feature produit à câbler ou test à supprimer."
)
@pytest.mark.asyncio
async def test_list_all_flags_agents_with_broken_profiles(db: None) -> None:
    """agents_service.list_all() must set has_errors=true on agents whose
    profiles reference documents that don't exist anymore."""
    from uuid import uuid4

    from agflow.services import agent_profiles_service, role_documents_service

    clean = await agents_service.create(
        AgentCreate(
            slug="clean",
            display_name="Clean",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    dirty = await agents_service.create(
        AgentCreate(
            slug="dirty",
            display_name="Dirty",
            dockerfile_id="claude-code",
            role_id="senior-dev",
        )
    )
    # clean agent has a profile with a real doc
    real_doc = await role_documents_service.create(
        role_id="senior-dev",
        section="roles",
        name="r1",
        content_md="ok",
    )
    await agent_profiles_service.create(
        agent_id=clean.id, name="ok", document_ids=[real_doc.id]
    )
    # dirty agent has a profile with a ghost UUID
    await agent_profiles_service.create(
        agent_id=dirty.id, name="ghost", document_ids=[uuid4()]
    )

    summaries = await agents_service.list_all()
    by_slug = {s.slug: s for s in summaries}
    assert by_slug["clean"].has_errors is False
    assert by_slug["dirty"].has_errors is True
