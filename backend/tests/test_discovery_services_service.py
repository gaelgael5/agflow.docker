from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.schemas.catalogs import ProbeResult  # noqa: E402
from agflow.services import discovery_services_service as svc  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    for t in [
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
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_get() -> None:
    created = await svc.create(
        service_id="yoops",
        name="yoops.org",
        base_url="https://mcp.yoops.org/api/v1",
        api_key_var="YOOPS_API_KEY",
    )
    assert created.id == "yoops"
    assert created.base_url == "https://mcp.yoops.org/api/v1"
    assert created.api_key_var == "YOOPS_API_KEY"

    again = await svc.get_by_id("yoops")
    assert again.name == "yoops.org"


@pytest.mark.asyncio
async def test_duplicate_raises() -> None:
    await svc.create(service_id="dup", name="d", base_url="https://x")
    with pytest.raises(svc.DuplicateDiscoveryServiceError):
        await svc.create(service_id="dup", name="d2", base_url="https://y")


@pytest.mark.asyncio
async def test_list_and_update_and_delete() -> None:
    await svc.create(service_id="a", name="Alpha", base_url="https://a")
    await svc.create(service_id="b", name="Beta", base_url="https://b")

    items = await svc.list_all()
    names = [i.name for i in items]
    assert "Alpha" in names and "Beta" in names

    updated = await svc.update("a", name="Alpha Renamed", enabled=False)
    assert updated.name == "Alpha Renamed"
    assert updated.enabled is False

    await svc.delete("b")
    with pytest.raises(svc.DiscoveryServiceNotFoundError):
        await svc.get_by_id("b")


@pytest.mark.asyncio
async def test_test_connectivity_with_missing_secret() -> None:
    await svc.create(
        service_id="with-key",
        name="k",
        base_url="https://x",
        api_key_var="NOT_IN_SECRETS",
    )
    result = await svc.test_connectivity("with-key")
    assert result.ok is False
    assert "NOT_IN_SECRETS" in result.detail


@pytest.mark.asyncio
async def test_test_connectivity_calls_probe() -> None:
    await svc.create(
        service_id="no-key", name="n", base_url="https://example.com"
    )

    with patch(
        "agflow.services.discovery_services_service.discovery_client.probe",
        new=AsyncMock(return_value=ProbeResult(ok=True, detail="OK")),
    ):
        result = await svc.test_connectivity("no-key")
    assert result.ok is True
    assert result.detail == "OK"
