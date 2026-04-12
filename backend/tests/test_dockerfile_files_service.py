from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import dockerfile_files_service as files  # noqa: E402
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
    await dockerfiles_service.create(dockerfile_id="test", display_name="Test")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_file() -> None:
    # The fixture auto-seeds Dockerfile + entrypoint.sh, so create a new one.
    f = await files.create(
        dockerfile_id="test",
        path="config.json",
        content="{}",
    )
    assert f.dockerfile_id == "test"
    assert f.path == "config.json"
    assert f.content == "{}"


@pytest.mark.asyncio
async def test_duplicate_path_raises() -> None:
    # Auto-seeded Dockerfile already exists from the fixture.
    with pytest.raises(files.DuplicateFileError):
        await files.create(dockerfile_id="test", path="Dockerfile", content="x")


@pytest.mark.asyncio
async def test_list_for_dockerfile() -> None:
    # The fixture auto-seeds the 3 standard files.
    items = await files.list_for_dockerfile("test")
    paths = {i.path for i in items}
    assert paths == {
        "Dockerfile",
        "entrypoint.sh",
        "Dockerfile.json",
    }


@pytest.mark.asyncio
async def test_protected_files_cannot_be_deleted() -> None:
    items = await files.list_for_dockerfile("test")
    by_path = {i.path: i for i in items}
    for protected in ("Dockerfile", "entrypoint.sh", "Dockerfile.json"):
        with pytest.raises(files.ProtectedFileError):
            await files.delete(by_path[protected].id)


@pytest.mark.asyncio
async def test_dockerfile_json_seeded_with_defaults() -> None:
    import json

    items = await files.list_for_dockerfile("test")
    dockerfile_json = next(i for i in items if i.path == "Dockerfile.json")
    parsed = json.loads(dockerfile_json.content)

    # Top-level shape: docker + Params
    assert set(parsed.keys()) == {"docker", "Params"}

    docker = parsed["docker"]
    assert docker["Container"] == {
        "Name": "agent-{slug}-{id}",
        "Image": "agflow-{slug}:{hash}",
    }
    assert docker["Network"] == {"Mode": "bridge"}
    assert docker["Runtime"] == {
        "Init": True,
        "StopSignal": "SIGTERM",
        "StopTimeout": 30,
        "WorkingDir": "/app",
    }
    assert docker["Resources"] == {"Memory": "2g", "Cpus": "1.5"}
    assert docker["Environments"] == {"ANTHROPIC_API_KEY": "{API_KEY_NAME}"}
    assert docker["Mounts"] == [
        {"source": "{WORKSPACE_PATH}", "target": "/app/workspace", "readonly": False},
        {"source": "./config", "target": "/app/config", "readonly": True},
        {"source": "./skills", "target": "/app/skills", "readonly": True},
        {"source": "./output", "target": "/app/output", "readonly": False},
    ]

    assert parsed["Params"] == {
        "API_KEY_NAME": "ANTHROPIC_API_KEY",
        "WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}",
    }


@pytest.mark.asyncio
async def test_update_content() -> None:
    f = await files.create(dockerfile_id="test", path="a.sh", content="old")
    updated = await files.update(f.id, content="new")
    assert updated.content == "new"


@pytest.mark.asyncio
async def test_delete_file() -> None:
    f = await files.create(dockerfile_id="test", path="x", content="")
    await files.delete(f.id)

    remaining = await files.list_for_dockerfile("test")
    assert all(fx.id != f.id for fx in remaining)


@pytest.mark.asyncio
async def test_get_by_id_missing() -> None:
    with pytest.raises(files.FileNotFoundError):
        await files.get_by_id(uuid.uuid4())
