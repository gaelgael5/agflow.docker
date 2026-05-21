# backend/tests/services/test_infra_env_vars_service.py
"""Tests d'intégration pour infra_env_vars_service (DB réelle)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import infra_env_vars_service as svc
from agflow.services.infra_env_vars_service import (
    EnvVarDuplicateError,
    EnvVarForeignKeyError,
    EnvVarNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _create_named_type() -> uuid.UUID:
    """Insère une catégorie + un named_type de test, retourne l'id du named_type."""
    # infra_categories(name PRIMARY KEY, is_vps boolean) — PAS de colonne 'label'
    await execute(
        "INSERT INTO infra_categories (name) VALUES ('test-cat') "
        "ON CONFLICT (name) DO NOTHING",
    )
    # infra_named_types.type_id = infra_categories.name (varchar FK)
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'Test NT', 'test-cat', 'SSH')",
        nt_id,
    )
    return nt_id


async def _create_machine(named_type_id: uuid.UUID) -> uuid.UUID:
    """Insère une machine de test liée au named_type.
    infra_machines.type_id = infra_named_types.id (UUID FK).
    """
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'test-machine', $2, '127.0.0.1', 22)",
        m_id, named_type_id,
    )
    return m_id


# ── CRUD named_type env vars ────────────────────────────────────────────────

async def test_create_and_list(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="MY_VAR", description="desc", position=1)
    assert ev.name == "MY_VAR"
    assert ev.named_type_id == nt_id
    rows = await svc.list_by_named_type(nt_id)
    assert len(rows) == 1
    assert rows[0].id == ev.id


async def test_get_by_id(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="VAR_A")
    fetched = await svc.get_env_var_by_id(ev.id)
    assert fetched.id == ev.id


async def test_get_by_id_not_found(fresh_db: None) -> None:
    with pytest.raises(EnvVarNotFoundError):
        await svc.get_env_var_by_id(uuid.uuid4())


async def test_update_env_var(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="OLD_NAME")
    updated = await svc.update_env_var(ev.id, name="NEW_NAME", description="updated")
    assert updated.name == "NEW_NAME"
    assert updated.description == "updated"


async def test_unique_constraint(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    await svc.create_env_var(nt_id, name="SAME")
    with pytest.raises(EnvVarDuplicateError):
        await svc.create_env_var(nt_id, name="SAME")


async def test_delete_env_var(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="TO_DELETE")
    await svc.delete_env_var(ev.id)
    with pytest.raises(EnvVarNotFoundError):
        await svc.get_env_var_by_id(ev.id)


async def test_cascade_delete_named_type(fresh_db: None) -> None:
    """Supprimer le named_type supprime ses env vars en cascade."""
    nt_id = await _create_named_type()
    await svc.create_env_var(nt_id, name="CASCADE_VAR")
    await execute("DELETE FROM infra_named_types WHERE id = $1", nt_id)
    rows = await svc.list_by_named_type(nt_id)
    assert rows == []


# ── machine env vars ────────────────────────────────────────────────────────

async def test_list_machine_env_vars_empty(fresh_db: None) -> None:
    """GET retourne les vars du contrat avec value='' si non remplies."""
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    await svc.create_env_var(nt_id, name="EMPTY_VAR")
    rows = await svc.list_machine_env_vars(m_id)
    assert len(rows) == 1
    assert rows[0].name == "EMPTY_VAR"
    assert rows[0].value == ""


async def test_upsert_machine_env_vars(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="MY_VAR")
    result = await svc.upsert_machine_env_vars(m_id, {ev.id: "hello"})
    assert len(result) == 1
    assert result[0].value == "hello"


async def test_upsert_idempotent(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="MY_VAR")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "first"})
    result = await svc.upsert_machine_env_vars(m_id, {ev.id: "second"})
    assert result[0].value == "second"
    # Vérifier qu'il n'y a pas de doublon
    rows_in_db = await fetch_one(
        "SELECT count(*) AS c FROM infra_machine_env_vars WHERE machine_id = $1", m_id,
    )
    assert rows_in_db is not None and rows_in_db["c"] == 1


async def test_upsert_invalid_id(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    with pytest.raises(EnvVarForeignKeyError):
        await svc.upsert_machine_env_vars(m_id, {uuid.uuid4(): "val"})


async def test_cascade_delete_machine(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="VAR")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "val"})
    await execute("DELETE FROM infra_machines WHERE id = $1", m_id)
    row = await fetch_one(
        "SELECT count(*) AS c FROM infra_machine_env_vars WHERE machine_id = $1", m_id,
    )
    assert row is not None and row["c"] == 0


async def test_resolve_for_machine_literal(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="HOST")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "example.com"})
    resolved = await svc.resolve_for_machine(m_id)
    assert resolved == {"HOST": "example.com"}


async def test_resolve_for_machine_excludes_empty(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    await svc.create_env_var(nt_id, name="EMPTY_HOST")
    resolved = await svc.resolve_for_machine(m_id)
    assert "EMPTY_HOST" not in resolved
