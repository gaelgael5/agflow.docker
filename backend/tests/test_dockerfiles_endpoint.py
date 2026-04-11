from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.main import create_app

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    await close_pool()


async def _token(c: AsyncClient) -> dict[str, str]:
    res = await c.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_dockerfile_and_list(client: AsyncClient) -> None:
    headers = await _token(client)

    create = await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "claude-code", "display_name": "Claude Code"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["id"] == "claude-code"
    assert body["display_status"] == "never_built"

    listing = await client.get("/api/admin/dockerfiles", headers=headers)
    assert listing.status_code == 200
    assert any(d["id"] == "claude-code" for d in listing.json())


@pytest.mark.asyncio
async def test_file_crud(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "df", "display_name": "DF"},
    )

    # Non-standard file — standard ones (Dockerfile, entrypoint.sh) are
    # auto-seeded at dockerfile creation.
    create_file = await client.post(
        "/api/admin/dockerfiles/df/files",
        headers=headers,
        json={"path": "config.json", "content": "{}"},
    )
    assert create_file.status_code == 201
    file_id = create_file.json()["id"]

    detail = await client.get("/api/admin/dockerfiles/df", headers=headers)
    assert detail.status_code == 200
    paths = [f["path"] for f in detail.json()["files"]]
    assert "Dockerfile" in paths
    assert "entrypoint.sh" in paths
    assert "config.json" in paths

    update_file = await client.put(
        f"/api/admin/dockerfiles/df/files/{file_id}",
        headers=headers,
        json={"content": '{"foo": 1}'},
    )
    assert update_file.status_code == 200
    assert update_file.json()["content"] == '{"foo": 1}'

    delete_file = await client.delete(
        f"/api/admin/dockerfiles/df/files/{file_id}", headers=headers
    )
    assert delete_file.status_code == 204


@pytest.mark.asyncio
async def test_create_dockerfile_auto_seeds_standard_files(
    client: AsyncClient,
) -> None:
    headers = await _token(client)
    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "autosd", "display_name": "Auto Seed"},
    )
    detail = await client.get(
        "/api/admin/dockerfiles/autosd", headers=headers
    )
    assert detail.status_code == 200
    files = detail.json()["files"]
    assert len(files) == 2
    paths = sorted(f["path"] for f in files)
    assert paths == ["Dockerfile", "entrypoint.sh"]
    assert all(f["content"] == "" for f in files)


@pytest.mark.asyncio
async def test_standard_files_cannot_be_deleted(client: AsyncClient) -> None:
    headers = await _token(client)
    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "prot", "display_name": "Prot"},
    )
    detail = await client.get(
        "/api/admin/dockerfiles/prot", headers=headers
    )
    dockerfile_file = next(
        f for f in detail.json()["files"] if f["path"] == "Dockerfile"
    )
    entrypoint_file = next(
        f for f in detail.json()["files"] if f["path"] == "entrypoint.sh"
    )

    for f in (dockerfile_file, entrypoint_file):
        res = await client.delete(
            f"/api/admin/dockerfiles/prot/files/{f['id']}", headers=headers
        )
        assert res.status_code == 403
        assert "standard file" in res.json()["detail"]


@pytest.mark.asyncio
async def test_build_endpoint_mocked(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "mdf", "display_name": "MockDF"},
    )
    await client.post(
        "/api/admin/dockerfiles/mdf/files",
        headers=headers,
        json={"path": "Dockerfile", "content": "FROM alpine"},
    )

    with patch(
        "agflow.api.admin.dockerfiles.build_service.run_build",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post(
            "/api/admin/dockerfiles/mdf/build", headers=headers
        )

    assert res.status_code == 202
    body = res.json()
    assert body["dockerfile_id"] == "mdf"
    assert body["status"] == "pending"
    assert body["image_tag"].startswith("agflow-mdf:")


@pytest.mark.asyncio
async def test_list_builds(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "lb", "display_name": "LB"},
    )
    await client.post(
        "/api/admin/dockerfiles/lb/files",
        headers=headers,
        json={"path": "Dockerfile", "content": "FROM alpine"},
    )

    with patch(
        "agflow.api.admin.dockerfiles.build_service.run_build",
        new=AsyncMock(return_value=None),
    ):
        await client.post("/api/admin/dockerfiles/lb/build", headers=headers)

    res = await client.get("/api/admin/dockerfiles/lb/builds", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 1


@pytest.mark.asyncio
async def test_delete_dockerfile_cascades_files(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "cas", "display_name": "Cas"},
    )
    await client.post(
        "/api/admin/dockerfiles/cas/files",
        headers=headers,
        json={"path": "Dockerfile", "content": ""},
    )

    delres = await client.delete("/api/admin/dockerfiles/cas", headers=headers)
    assert delres.status_code == 204

    listing = await client.get("/api/admin/dockerfiles", headers=headers)
    assert all(d["id"] != "cas" for d in listing.json())
