"""group_scripts — liaison script ↔ groupe avec contexte d'exécution.

Une ligne `group_scripts` indique :
  * quel script s'exécute,
  * quand (`timing` ∈ {before, after}),
  * sur quelle machine cible (`target_kind`) :
      - `fixed_machine`     → la machine désignée par `machine_id` (UUID fixe)
      - `deployment_host`   → la machine assignée au groupe au runtime
        (résolu via `resolve_target_machine_id` → `groups.machine_id`).
"""
from __future__ import annotations

import json as _json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.scripts import GroupScriptRow, TriggerRule

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        gs.id, gs.group_id, gs.script_id, gs.target_kind, gs.machine_id,
        gs.timing, gs.position,
        gs.env_mapping, gs.input_values, gs.input_statuses, gs.trigger_rules,
        gs.created_at, gs.updated_at,
        s.name AS script_name,
        m.name AS machine_name_raw, m.host AS machine_host,
        g.name AS group_name
    FROM group_scripts gs
    JOIN scripts s ON s.id = gs.script_id
    LEFT JOIN infra_machines m ON m.id = gs.machine_id
    JOIN groups g ON g.id = gs.group_id
"""


class GroupScriptNotFoundError(Exception):
    pass


class GroupScriptInvalidTargetError(ValueError):
    """target_kind='fixed_machine' sans machine_id, ou target_kind invalide."""


class GroupScriptNoDeploymentHostError(RuntimeError):
    """target_kind='deployment_host' mais le groupe n'a pas de machine assignée."""


def _to_row(row: dict[str, Any]) -> GroupScriptRow:
    mapping = row.get("env_mapping") or {}
    if isinstance(mapping, str):
        mapping = _json.loads(mapping)
    inputs = row.get("input_values") or {}
    if isinstance(inputs, str):
        inputs = _json.loads(inputs)
    statuses = row.get("input_statuses") or {}
    if isinstance(statuses, str):
        statuses = _json.loads(statuses)
    rules_raw = row.get("trigger_rules") or []
    if isinstance(rules_raw, str):
        rules_raw = _json.loads(rules_raw)
    rules = [
        TriggerRule(
            variable=r.get("variable", ""),
            op=r.get("op", "equals"),
            value=r.get("value", ""),
        )
        for r in rules_raw
        if r.get("variable")
    ]
    machine_name = row.get("machine_name_raw") or row.get("machine_host") or ""
    return GroupScriptRow(
        id=row["id"],
        group_id=row["group_id"],
        group_name=row.get("group_name", ""),
        script_id=row["script_id"],
        script_name=row["script_name"],
        target_kind=row.get("target_kind") or "fixed_machine",
        machine_id=row.get("machine_id"),
        machine_name=machine_name,
        timing=row["timing"],
        position=row["position"],
        env_mapping=mapping,
        input_values=inputs,
        input_statuses=statuses,
        trigger_rules=rules,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_by_group(group_id: UUID) -> list[GroupScriptRow]:
    rows = await fetch_all(
        _LIST_SQL + " WHERE gs.group_id = $1 ORDER BY gs.timing, gs.position, s.name",
        group_id,
    )
    return [_to_row(r) for r in rows]


async def get_by_id(link_id: UUID) -> GroupScriptRow:
    row = await fetch_one(_LIST_SQL + " WHERE gs.id = $1", link_id)
    if row is None:
        raise GroupScriptNotFoundError(f"group_script {link_id} not found")
    return _to_row(row)


def _serialize_trigger_rules(rules: Any) -> str:
    if not rules:
        return "[]"
    out = []
    for r in rules:
        if hasattr(r, "model_dump"):
            out.append(r.model_dump())
        elif isinstance(r, dict):
            out.append({
                "variable": r.get("variable", ""),
                "op": r.get("op", "equals"),
                "value": r.get("value", ""),
            })
    return _json.dumps(out)


def _validate_target(target_kind: str, machine_id: UUID | None) -> None:
    if target_kind not in ("fixed_machine", "deployment_host"):
        raise GroupScriptInvalidTargetError(
            f"target_kind must be 'fixed_machine' or 'deployment_host', got {target_kind!r}"
        )
    if target_kind == "fixed_machine" and machine_id is None:
        raise GroupScriptInvalidTargetError(
            "target_kind='fixed_machine' requires machine_id to be set"
        )


async def create(
    group_id: UUID,
    script_id: UUID,
    machine_id: UUID | None,
    timing: str,
    position: int = 0,
    env_mapping: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
    input_statuses: dict[str, str] | None = None,
    trigger_rules: Any = None,
    target_kind: str = "fixed_machine",
) -> GroupScriptRow:
    _validate_target(target_kind, machine_id)
    effective_machine_id = machine_id if target_kind == "fixed_machine" else None
    row = await fetch_one(
        """
        INSERT INTO group_scripts
            (group_id, script_id, target_kind, machine_id, timing, position,
             env_mapping, input_values, input_statuses, trigger_rules)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb)
        RETURNING id
        """,
        group_id, script_id, target_kind, effective_machine_id, timing, position,
        _json.dumps(env_mapping or {}),
        _json.dumps(input_values or {}),
        _json.dumps(input_statuses or {}),
        _serialize_trigger_rules(trigger_rules),
    )
    assert row is not None
    _log.info(
        "group_scripts.create",
        group_id=str(group_id),
        script_id=str(script_id),
        target_kind=target_kind,
    )
    return await get_by_id(row["id"])


async def update(link_id: UUID, **kwargs: Any) -> GroupScriptRow:
    current = await get_by_id(link_id)

    # Détermine le state effectif après update pour la validation cohérente
    # (target_kind + machine_id doivent rester compatibles).
    next_target_kind = kwargs.get("target_kind") or current.target_kind
    next_machine_id: UUID | None
    if "machine_id" in kwargs:
        next_machine_id = kwargs["machine_id"]
    else:
        next_machine_id = current.machine_id
    if next_target_kind == "deployment_host":
        # En deployment_host on ignore machine_id (résolu au runtime).
        next_machine_id = None
    _validate_target(next_target_kind, next_machine_id)

    updates: dict[str, Any] = {}
    jsonb_fields: set[str] = set()
    if "script_id" in kwargs and kwargs["script_id"] is not None:
        updates["script_id"] = kwargs["script_id"]
    if "timing" in kwargs and kwargs["timing"] is not None:
        updates["timing"] = kwargs["timing"]
    if "position" in kwargs and kwargs["position"] is not None:
        updates["position"] = kwargs["position"]
    if "target_kind" in kwargs and kwargs["target_kind"] is not None:
        updates["target_kind"] = kwargs["target_kind"]
    # machine_id : toujours réécrit pour respecter next_machine_id
    # (None en deployment_host, valeur fournie sinon).
    if "machine_id" in kwargs or "target_kind" in kwargs:
        updates["machine_id"] = next_machine_id
    if "env_mapping" in kwargs and kwargs["env_mapping"] is not None:
        updates["env_mapping"] = _json.dumps(kwargs["env_mapping"])
        jsonb_fields.add("env_mapping")
    if "input_values" in kwargs and kwargs["input_values"] is not None:
        updates["input_values"] = _json.dumps(kwargs["input_values"])
        jsonb_fields.add("input_values")
    if "input_statuses" in kwargs and kwargs["input_statuses"] is not None:
        updates["input_statuses"] = _json.dumps(kwargs["input_statuses"])
        jsonb_fields.add("input_statuses")
    if "trigger_rules" in kwargs and kwargs["trigger_rules"] is not None:
        updates["trigger_rules"] = _serialize_trigger_rules(kwargs["trigger_rules"])
        jsonb_fields.add("trigger_rules")

    if not updates:
        return current

    sets = []
    values = []
    for i, (k, v) in enumerate(updates.items(), 2):
        if k in jsonb_fields:
            sets.append(f"{k} = ${i}::jsonb")
        else:
            sets.append(f"{k} = ${i}")
        values.append(v)

    await execute(
        f"UPDATE group_scripts SET {', '.join(sets)} WHERE id = $1",
        link_id, *values,
    )
    _log.info("group_scripts.update", id=str(link_id))
    return await get_by_id(link_id)


async def delete(link_id: UUID) -> None:
    result = await execute("DELETE FROM group_scripts WHERE id = $1", link_id)
    if result.endswith(" 0"):
        raise GroupScriptNotFoundError(f"group_script {link_id} not found")
    _log.info("group_scripts.delete", id=str(link_id))


async def resolve_target_machine_id(link_id: UUID) -> UUID:
    """Retourne la machine effective où exécuter le script.

    - target_kind='fixed_machine'    → row.machine_id (jamais NULL grâce au CHECK DB)
    - target_kind='deployment_host'  → groups.machine_id (résolu maintenant)

    Lève GroupScriptNoDeploymentHostError si `deployment_host` mais
    `groups.machine_id` est NULL (le groupe n'a pas encore de machine assignée).
    """
    row = await fetch_one(
        """
        SELECT gs.target_kind, gs.machine_id, g.machine_id AS group_machine_id
        FROM group_scripts gs
        JOIN groups g ON g.id = gs.group_id
        WHERE gs.id = $1
        """,
        link_id,
    )
    if row is None:
        raise GroupScriptNotFoundError(f"group_script {link_id} not found")
    if row["target_kind"] == "deployment_host":
        if row["group_machine_id"] is None:
            raise GroupScriptNoDeploymentHostError(
                f"group_script {link_id} uses deployment_host but the group "
                "has no machine assigned yet"
            )
        return row["group_machine_id"]
    return row["machine_id"]
