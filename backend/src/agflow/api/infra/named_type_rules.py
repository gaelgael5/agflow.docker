from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import NamedTypeRuleCreate, NamedTypeRuleRow

router = APIRouter(
    prefix="/api/infra/named-types/{named_type_id}/rules",
    tags=["infra-named-type-rules"],
)

router_all = APIRouter(
    prefix="/api/infra/named-type-rules",
    tags=["infra-named-type-rules"],
)

_admin = [Depends(require_admin)]


@router_all.get("", response_model=list[NamedTypeRuleRow], dependencies=_admin)
async def list_all_rules():
    rows = await fetch_all(
        "SELECT id, named_type_id, key, value, created_at"
        " FROM infra_named_type_rules ORDER BY named_type_id, key",
    )
    return [NamedTypeRuleRow(**r) for r in rows]


@router.get("", response_model=list[NamedTypeRuleRow], dependencies=_admin)
async def list_rules(named_type_id: UUID):
    rows = await fetch_all(
        "SELECT id, named_type_id, key, value, created_at"
        " FROM infra_named_type_rules"
        " WHERE named_type_id = $1 ORDER BY key",
        named_type_id,
    )
    return [NamedTypeRuleRow(**r) for r in rows]


@router.post(
    "",
    response_model=NamedTypeRuleRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=_admin,
)
async def create_rule(named_type_id: UUID, payload: NamedTypeRuleCreate):
    try:
        row = await fetch_one(
            """
            INSERT INTO infra_named_type_rules (named_type_id, key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (named_type_id, key) DO UPDATE SET value = $3
            RETURNING id, named_type_id, key, value, created_at
            """,
            named_type_id, payload.key, payload.value,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    return NamedTypeRuleRow(**row)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_rule(named_type_id: UUID, rule_id: UUID):
    result = await execute(
        "DELETE FROM infra_named_type_rules WHERE id = $1 AND named_type_id = $2",
        rule_id, named_type_id,
    )
    if result.endswith(" 0"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
