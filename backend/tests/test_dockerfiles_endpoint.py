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
    paths = sorted(f["path"] for f in files)
    assert paths == [
        "Dockerfile",
        "Dockerfile.json",
        "entrypoint.sh",
    ]
    by_path = {f["path"]: f for f in files}
    # Dockerfile + entrypoint.sh are seeded empty; the user fills them in.
    assert by_path["Dockerfile"]["content"] == ""
    assert by_path["entrypoint.sh"]["content"] == ""
    # Dockerfile.json comes with default content.
    assert '"docker"' in by_path["Dockerfile.json"]["content"]


@pytest.mark.asyncio
async def test_protected_files_cannot_be_deleted(client: AsyncClient) -> None:
    headers = await _token(client)
    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "prot", "display_name": "Prot"},
    )
    detail = await client.get(
        "/api/admin/dockerfiles/prot", headers=headers
    )
    files_by_path = {f["path"]: f for f in detail.json()["files"]}

    for path in ("Dockerfile", "entrypoint.sh", "Dockerfile.json"):
        file = files_by_path[path]
        res = await client.delete(
            f"/api/admin/dockerfiles/prot/files/{file['id']}", headers=headers
        )
        assert res.status_code == 403, f"{path} should be protected"
        assert "protected" in res.json()["detail"].lower()


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
async def test_export_returns_zip_with_all_files(client: AsyncClient) -> None:
    import io
    import zipfile

    headers = await _token(client)
    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "exp", "display_name": "Export Test"},
    )
    # Fill the standard Dockerfile + add a custom file
    detail = (
        await client.get("/api/admin/dockerfiles/exp", headers=headers)
    ).json()
    dockerfile_file = next(
        f for f in detail["files"] if f["path"] == "Dockerfile"
    )
    await client.put(
        f"/api/admin/dockerfiles/exp/files/{dockerfile_file['id']}",
        headers=headers,
        json={"content": "FROM alpine:3.20"},
    )
    await client.post(
        "/api/admin/dockerfiles/exp/files",
        headers=headers,
        json={"path": "config.json", "content": '{"foo": 1}'},
    )

    res = await client.get(
        "/api/admin/dockerfiles/exp/export", headers=headers
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert 'attachment; filename="exp.zip"' in res.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            "Dockerfile",
            "entrypoint.sh",
            "Dockerfile.json",
            "config.json",
        }
        assert zf.read("Dockerfile").decode() == "FROM alpine:3.20"
        assert zf.read("config.json").decode() == '{"foo": 1}'


@pytest.mark.asyncio
async def test_export_not_found_returns_404(client: AsyncClient) -> None:
    headers = await _token(client)
    res = await client.get(
        "/api/admin/dockerfiles/does-not-exist/export", headers=headers
    )
    assert res.status_code == 404


# ─────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────

_VALID_DOCKERFILE_JSON = '{\n  "docker": {"Container": {}},\n  "Params": {}\n}\n'


def _make_zip(entries: dict[str, str]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries.items():
            zf.writestr(path, content)
    return buf.getvalue()


async def _create_and_add_custom(
    client: AsyncClient, headers: dict[str, str], dockerfile_id: str
) -> None:
    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": dockerfile_id, "display_name": dockerfile_id},
    )
    # Drop a custom file to make sure it gets wiped on import.
    await client.post(
        f"/api/admin/dockerfiles/{dockerfile_id}/files",
        headers=headers,
        json={"path": "leftover.txt", "content": "should be gone after import"},
    )


@pytest.mark.asyncio
async def test_import_happy_path(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "imphp")

    zip_bytes = _make_zip(
        {
            "Dockerfile": "FROM python:3.12-slim",
            "entrypoint.sh": "#!/bin/sh\nexec python app.py",
            "Dockerfile.json": _VALID_DOCKERFILE_JSON,
            "run.cmd.md": "# custom run doc",
            "config.json": '{"x": 1}',
        }
    )

    res = await client.post(
        "/api/admin/dockerfiles/imphp/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 200, res.text

    body = res.json()
    paths = sorted(f["path"] for f in body["files"])
    assert paths == [
        "Dockerfile",
        "Dockerfile.json",
        "config.json",
        "entrypoint.sh",
        "run.cmd.md",
    ]
    # Leftover from before the import must be gone.
    assert "leftover.txt" not in paths
    # Content has been replaced.
    dockerfile_file = next(f for f in body["files"] if f["path"] == "Dockerfile")
    assert dockerfile_file["content"] == "FROM python:3.12-slim"


@pytest.mark.asyncio
async def test_import_missing_required_files(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "impmiss")

    zip_bytes = _make_zip({"Dockerfile": "FROM alpine"})  # missing 2 others

    res = await client.post(
        "/api/admin/dockerfiles/impmiss/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 400
    errors = res.json()["detail"]["errors"]
    joined = " ".join(errors)
    assert "entrypoint.sh" in joined
    assert "Dockerfile.json" in joined


@pytest.mark.asyncio
async def test_import_invalid_dockerfile_json(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "impinv")

    zip_bytes = _make_zip(
        {
            "Dockerfile": "FROM alpine",
            "entrypoint.sh": "#!/bin/sh",
            "Dockerfile.json": "{not valid json",
        }
    )

    res = await client.post(
        "/api/admin/dockerfiles/impinv/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 400
    errors = res.json()["detail"]["errors"]
    assert any("JSON valide" in e for e in errors)


@pytest.mark.asyncio
async def test_import_wrong_dockerfile_json_shape(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "impshape")

    zip_bytes = _make_zip(
        {
            "Dockerfile": "FROM alpine",
            "entrypoint.sh": "#!/bin/sh",
            # Missing 'docker' and 'Params' keys.
            "Dockerfile.json": '{"Arguments": {}}',
        }
    )

    res = await client.post(
        "/api/admin/dockerfiles/impshape/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 400
    errors = res.json()["detail"]["errors"]
    assert any("'docker'" in e for e in errors)
    assert any("'Params'" in e for e in errors)


@pytest.mark.asyncio
async def test_import_not_a_zip(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "impbad")

    res = await client.post(
        "/api/admin/dockerfiles/impbad/import",
        headers=headers,
        files={"file": ("not-a-zip.bin", b"definitely not a zip", "application/zip")},
    )
    assert res.status_code == 400
    errors = res.json()["detail"]["errors"]
    assert any("zip" in e.lower() for e in errors)


@pytest.mark.asyncio
async def test_import_rejects_subdirectories(client: AsyncClient) -> None:
    headers = await _token(client)
    await _create_and_add_custom(client, headers, "impsub")

    zip_bytes = _make_zip(
        {
            "Dockerfile": "FROM alpine",
            "entrypoint.sh": "#!/bin/sh",
            "Dockerfile.json": _VALID_DOCKERFILE_JSON,
            "scripts/helper.sh": "#!/bin/sh",
        }
    )

    res = await client.post(
        "/api/admin/dockerfiles/impsub/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 400
    errors = res.json()["detail"]["errors"]
    assert any("sous-répertoire" in e for e in errors)


@pytest.mark.asyncio
async def test_import_not_found(client: AsyncClient) -> None:
    headers = await _token(client)
    zip_bytes = _make_zip(
        {
            "Dockerfile": "FROM alpine",
            "entrypoint.sh": "#!/bin/sh",
            "Dockerfile.json": _VALID_DOCKERFILE_JSON,
        }
    )
    res = await client.post(
        "/api/admin/dockerfiles/does-not-exist/import",
        headers=headers,
        files={"file": ("archive.zip", zip_bytes, "application/zip")},
    )
    assert res.status_code == 404


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
