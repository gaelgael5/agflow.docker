"""Tests d'integration de infra_machines_service."""

from __future__ import annotations

import uuid

import pytest

from agflow.db.pool import execute
from agflow.services import infra_machines_service as svc
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


class TestGetByName:
    pytestmark = pytest.mark.asyncio

    async def test_returns_machine_by_unique_name(self, fresh_db) -> None:
        await execute(
            "INSERT INTO infra_categories (name) VALUES ('test-cat') ON CONFLICT (name) DO NOTHING",
        )
        nt_id = uuid.uuid4()
        await execute(
            "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
            "VALUES ($1, 'NT', 'test-cat', 'SSH')",
            nt_id,
        )
        m_id = uuid.uuid4()
        await execute(
            "INSERT INTO infra_machines (id, name, type_id, host, port) "
            "VALUES ($1, 'lookup-target', $2, '127.0.0.1', 22)",
            m_id,
            nt_id,
        )

        result = await svc.get_by_name("lookup-target")
        assert result is not None
        assert result.id == m_id
        assert result.name == "lookup-target"

    async def test_returns_none_for_unknown_name(self, fresh_db) -> None:
        assert await svc.get_by_name("does-not-exist") is None
