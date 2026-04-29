"""group_scripts — liaison script ↔ groupe avec contexte d'exécution."""
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
        gs.id, gs.group_id, gs.script_id, gs.machine_id, gs.timing, gs.position,
        gs.env_mapping, gs.input_values, gs.input_statuses, gs.trigger_rules,
        gs.created_at, gs.updated_at,
        s.name AS script_name,
        m.name AS machine_name_raw, m.host AS machine_host,
        g.name AS group_name
    FROM group_scripts gs
    JOIN scripts s ON s.id = gs.script_id
    JOIN infra_machines m ON m.id = gs.machine_id
    JOIN groups g ON g.id = gs.group_id
"""


class GroupScriptNotFoundError(Exception):
    pass


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
        machine_id=row["machine_id"],
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


async def create(
    group_id: UUID,
    script_id: UUID,
    machine_id: UUID,
    timing: str,
    position: int = 0,
    env_mapping: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
    input_statuses: dict[str, str] | None = None,
    trigger_rules: Any = None,
) -> GroupScriptRow:
    row = await fetch_one(
        """
        INSERT INTO group_scripts
            (group_id, script_id, machine_id, timing, position,
             env_mapping, input_values, input_statuses, trigger_rules)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb)
        RETURNING id
        """,
        group_id, script_id, machine_id, timing, position,
        _json.dumps(env_mapping or {}),
        _json.dumps(input_values or {}),
        _json.dumps(input_statuses or {}),
        _serialize_trigger_rules(trigger_rules),
    )
    assert row is not None
    _log.info("group_scripts.create", group_id=str(group_id), script_id=str(script_id))
    return await get_by_id(row["id"])


async def update(link_id: UUID, **kwargs: Any) -> GroupScriptRow:
    await get_by_id(link_id)

    updates: dict[str, Any] = {}
    jsonb_fields: set[str] = set()
    for field in ("script_id", "machine_id", "timing", "position"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]
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
        return await get_by_id(link_id)

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
