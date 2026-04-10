from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.main import create_app
from agflow.services import prompt_generator

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await close_pool()


async def _token(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_role_and_list(client: AsyncClient) -> None:
    headers = await _token(client)

    create = await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "analyst", "display_name": "Analyst"},
    )
    assert create.status_code == 201, create.text
    assert create.json()["id"] == "analyst"

    listing = await client.get("/api/admin/roles", headers=headers)
    assert listing.status_code == 200
    assert any(r["id"] == "analyst" for r in listing.json())


@pytest.mark.asyncio
async def test_get_role_detail_includes_documents(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "analyst", "display_name": "Analyst"},
    )
    await client.post(
        "/api/admin/roles/analyst/documents",
        headers=headers,
        json={"section": "roles", "name": "r1", "content_md": "Tu analyses."},
    )
    await client.post(
        "/api/admin/roles/analyst/documents",
        headers=headers,
        json={"section": "missions", "name": "m1", "content_md": "Tu transformes."},
    )

    res = await client.get("/api/admin/roles/analyst", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["role"]["id"] == "analyst"
    assert len(body["roles_documents"]) == 1
    assert len(body["missions_documents"]) == 1
    assert len(body["competences_documents"]) == 0


@pytest.mark.asyncio
async def test_update_and_delete_role(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "tmp", "display_name": "Tmp"},
    )

    upd = await client.put(
        "/api/admin/roles/tmp",
        headers=headers,
        json={"display_name": "Updated"},
    )
    assert upd.status_code == 200
    assert upd.json()["display_name"] == "Updated"

    delres = await client.delete("/api/admin/roles/tmp", headers=headers)
    assert delres.status_code == 204

    listing = await client.get("/api/admin/roles", headers=headers)
    assert all(r["id"] != "tmp" for r in listing.json())


@pytest.mark.asyncio
async def test_document_protected_flag_blocks_update(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "r1", "display_name": "R1"},
    )
    create_doc = await client.post(
        "/api/admin/roles/r1/documents",
        headers=headers,
        json={
            "section": "roles",
            "name": "locked",
            "content_md": "original",
            "protected": True,
        },
    )
    doc_id = create_doc.json()["id"]

    blocked = await client.put(
        f"/api/admin/roles/r1/documents/{doc_id}",
        headers=headers,
        json={"content_md": "should fail"},
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_generate_prompts_uses_mocked_anthropic(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={
            "id": "gen",
            "display_name": "Gen",
            "identity_md": "Tu es rigoureux.",
        },
    )

    mock_result = prompt_generator.GeneratedPrompts(
        prompt_orchestrator_md="Il est un assistant rigoureux et direct.",
    )

    with patch(
        "agflow.api.admin.roles.prompt_generator.generate_prompts",
        new=AsyncMock(return_value=mock_result),
    ):
        res = await client.post(
            "/api/admin/roles/gen/generate-prompts",
            headers=headers,
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["prompt_orchestrator_md"].startswith("Il est")
    assert "prompt_agent_md" not in body


@pytest.mark.asyncio
async def test_generate_prompts_missing_anthropic_key(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "nokey", "display_name": "NoKey"},
    )

    with patch(
        "agflow.api.admin.roles.prompt_generator.generate_prompts",
        new=AsyncMock(
            side_effect=prompt_generator.MissingAnthropicKeyError(
                "ANTHROPIC_API_KEY is not set"
            )
        ),
    ):
        res = await client.post(
            "/api/admin/roles/nokey/generate-prompts",
            headers=headers,
        )

    assert res.status_code == 412
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]
