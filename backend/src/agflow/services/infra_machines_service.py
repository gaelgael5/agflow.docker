"""Infrastructure machines service — asyncpg CRUD.

Passwords are stored in Harpocrate vault; a vault ref is persisted in DB.
Table unifiée (ex-infra_servers + ex-infra_machines depuis la migration 064).
"""
from __future__ import annotations

import json as _json
import re
import uuid as _uuid
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import MachineSummary, RequiredActionStatus
from agflow.services import vault_client

_VAULT_REF_RE = re.compile(r"^\$\{vault://([^:]+):(.+)\}$")


def _vault_path(machine_id: _uuid.UUID) -> str:
    return f"machines/{machine_id}/password"


def _vault_ref(machine_id: _uuid.UUID) -> str:
    return f"${{vault://HARPOCRATE_KEY:{_vault_path(machine_id)}}}"


def _parse_vault_ref(value: str | None) -> str | None:
    """Retourne le chemin vault si value est un vault ref, sinon None."""
    if not value:
        return None
    m = _VAULT_REF_RE.match(value)
    return m.group(2) if m else None

_log = structlog.get_logger(__name__)

# Jointure : machine + named_type → category.
# Le label humain de la variante vient de infra_named_types.name,
# la catégorie de infra_named_types.type_id (FK infra_categories.name).
_LIST_SQL = """
    SELECT
        m.id, m.name, m.type_id, m.host, m.port, m.username, m.password,
        m.certificate_id, m.parent_id, m.user_id, m.environment,
        m.metadata, m.status,
        m.created_at, m.updated_at,
        nt.name AS type_name,
        nt.type_id AS category,
        coalesce(c.cnt, 0) AS children_count,
        coalesce(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'name', ca.name,
                        'done', EXISTS (
                            SELECT 1
                            FROM infra_named_type_actions nta
                            JOIN infra_machines_runs r
                                 ON r.action_id = nta.id AND r.machine_id = m.id
                            WHERE nta.named_type_id = m.type_id
                              AND nta.category_action_id = ca.id
                              AND r.success = true
                        )
                    ) ORDER BY ca.name
                )
                FROM infra_category_actions ca
                WHERE ca.category = nt.type_id
                  AND ca.is_required = true
            ),
            '[]'::jsonb
        ) AS required_actions
    FROM infra_machines m
    JOIN infra_named_types nt ON nt.id = m.type_id
    LEFT JOIN (
        SELECT parent_id, count(*) AS cnt
        FROM infra_machines
        WHERE parent_id IS NOT NULL
        GROUP BY parent_id
    ) c ON c.parent_id = m.id
"""


class MachineNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> MachineSummary:
    raw_meta = row.get("metadata") or {}
    if isinstance(raw_meta, str):
        raw_meta = _json.loads(raw_meta)
    raw_required = row.get("required_actions") or []
    if isinstance(raw_required, str):
        raw_required = _json.loads(raw_required)
    required = [
        RequiredActionStatus(name=a["name"], done=bool(a.get("done")))
        for a in raw_required
    ]
    return MachineSummary(
        id=row["id"],
        name=row.get("name", ""),
        type_id=row["type_id"],
        type_name=row["type_name"],
        category=row["category"],
        host=row["host"],
        port=row["port"],
        username=row["username"],
        has_password=bool(row.get("password")),
        certificate_id=row.get("certificate_id"),
        parent_id=row.get("parent_id"),
        user_id=row.get("user_id"),
        environment=row.get("environment"),
        children_count=row.get("children_count", 0),
        metadata=raw_meta,
        status=row.get("status", "not_initialized"),
        required_actions=required,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_all() -> list[MachineSummary]:
    rows = await fetch_all(_LIST_SQL + " ORDER BY m.host")
    return [_to_summary(r) for r in rows]


async def get_by_id(machine_id: UUID) -> MachineSummary:
    row = await fetch_one(_LIST_SQL + " WHERE m.id = $1", machine_id)
    if row is None:
        raise MachineNotFoundError(f"Machine {machine_id} not found")
    return _to_summary(row)


async def get_credentials(machine_id: UUID) -> dict[str, Any]:
    """Return credentials for SSH use. Password fetched from Harpocrate."""
    row = await fetch_one(
        "SELECT host, port, username, password, certificate_id FROM infra_machines WHERE id = $1",
        machine_id,
    )
    if row is None:
        raise MachineNotFoundError(f"Machine {machine_id} not found")

    plain_password: str | None = None
    path = _parse_vault_ref(row["password"])
    if path:
        plain_password = await vault_client.get_secret(path)

    return {
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "password": plain_password,
        "certificate_id": row.get("certificate_id"),
    }


async def create(
    type_id: UUID,
    host: str,
    port: int = 22,
    username: str | None = None,
    password: str | None = None,
    certificate_id: UUID | None = None,
    name: str = "",
    metadata: dict | None = None,
    parent_id: UUID | None = None,
    user_id: UUID | None = None,
    environment: str | None = None,
) -> MachineSummary:
    row = await fetch_one(
        """
        INSERT INTO infra_machines
            (name, type_id, host, port, username,
             certificate_id, parent_id, metadata, user_id, environment)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
        RETURNING id
        """,
        name, type_id, host, port, username,
        certificate_id, parent_id,
        _json.dumps(metadata or {}),
        user_id, environment,
    )
    assert row is not None
    machine_id: _uuid.UUID = row["id"]

    if password is not None:
        secret_created = False
        try:
            await vault_client.create_secret(_vault_path(machine_id), password)
            secret_created = True
            await execute(
                "UPDATE infra_machines SET password = $1 WHERE id = $2",
                _vault_ref(machine_id), machine_id,
            )
        except Exception:
            if secret_created:
                try:
                    await vault_client.delete_secret(_vault_path(machine_id))
                except Exception:
                    _log.warning(
                        "infra_machines.vault_rollback_failed",
                        machine_id=str(machine_id),
                    )
            await execute("DELETE FROM infra_machines WHERE id = $1", machine_id)
            raise

    _log.info("infra_machines.create", host=host, type_id=str(type_id))
    return await get_by_id(machine_id)


async def update(machine_id: UUID, **kwargs: Any) -> MachineSummary:
    await get_by_id(machine_id)

    # Gérer le password séparément (vault)
    new_password: str | None = kwargs.pop("password", None)
    if new_password is not None:
        pw_row = await fetch_one(
            "SELECT password FROM infra_machines WHERE id = $1", machine_id
        )
        existing_path = _parse_vault_ref(pw_row["password"] if pw_row else None)
        if existing_path:
            await vault_client.update_secret(existing_path, new_password)
        else:
            await vault_client.create_secret(_vault_path(machine_id), new_password)
            await execute(
                "UPDATE infra_machines SET password = $1 WHERE id = $2",
                _vault_ref(machine_id), machine_id,
            )

    # Autres champs (sans password)
    updates: dict[str, Any] = {}
    for field in ("name", "host", "port", "username", "certificate_id", "user_id", "environment"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if updates:
        sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
        await execute(
            f"UPDATE infra_machines SET {', '.join(sets)} WHERE id = $1",
            machine_id, *updates.values(),
        )

    _log.info("infra_machines.update", id=str(machine_id))
    return await get_by_id(machine_id)


async def update_status(machine_id: UUID, status: str) -> None:
    await execute(
        "UPDATE infra_machines SET status = $1 WHERE id = $2",
        status, machine_id,
    )
    _log.info("infra_machines.status_updated", id=str(machine_id), status=status)


async def merge_metadata(machine_id: UUID, updates: dict) -> None:
    """Merge new keys into the machine's existing metadata JSONB."""
    await execute(
        "UPDATE infra_machines SET metadata = metadata || $2::jsonb WHERE id = $1",
        machine_id, _json.dumps(updates),
    )
    _log.info("infra_machines.merge_metadata", id=str(machine_id), keys=list(updates.keys()))


async def delete(machine_id: UUID) -> None:
    # Lire le vault ref AVANT de supprimer
    pw_row = await fetch_one(
        "SELECT password FROM infra_machines WHERE id = $1", machine_id
    )
    path = _parse_vault_ref(pw_row["password"] if pw_row else None)

    row = await fetch_one(
        "DELETE FROM infra_machines WHERE id = $1 RETURNING id", machine_id,
    )
    if row is None:
        raise MachineNotFoundError(f"Machine {machine_id} not found")

    if path:
        try:
            await vault_client.delete_secret(path)
        except Exception:
            _log.warning("infra_machines.vault_delete_failed", id=str(machine_id), path=path)

    _log.info("infra_machines.delete", id=str(machine_id))


async def get_for_user(
    user_id: UUID, environment: str | None,
) -> MachineSummary | None:
    """Return the machine assigned to (user_id, environment), or None if absent.

    Used by the SaaS runtime creation flow to resolve which machine hosts a
    given user's runtime for a given environment. Unique by (user_id,
    environment) — see migration 085.
    """
    row = await fetch_one(
        _LIST_SQL + " WHERE m.user_id = $1 AND m.environment IS NOT DISTINCT FROM $2",
        user_id, environment,
    )
    if row is None:
        return None
    return _to_summary(row)


# ── B0 : ingestion JSON create-swarm-lxc → colonnes 1st-class + metadata ──
# Fonctions déplacées dans infra_machines_ingest.py (limite 300 lignes).

from agflow.services.infra_machines_ingest import (  # noqa: F401, E402  (re-export)
    derive_machine_columns_from_output,
    derive_metadata_from_output,
)
