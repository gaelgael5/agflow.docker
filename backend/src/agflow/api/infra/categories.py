from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import CategoryActionRow, CategoryRow

router = APIRouter(prefix="/api/infra/categories", tags=["infra-categories"])

_ACTION_SELECT = """
    SELECT a.id, a.name, a.is_required, a.creates_named_type_id,
           nt.name AS creates_named_type_name
    FROM infra_category_actions a
    LEFT JOIN infra_named_types nt ON nt.id = a.creates_named_type_id
"""


def _action_row(r) -> CategoryActionRow:
    return CategoryActionRow(**dict(r))


@router.get("", response_model=list[CategoryRow], dependencies=[Depends(require_admin)])
async def list_categories():
    rows = await fetch_all("SELECT name FROM infra_categories ORDER BY name")
    return [CategoryRow(**r) for r in rows]


class CategoryCreate(BaseModel):
    name: str


@router.post(
    "",
    response_model=CategoryRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_category(payload: CategoryCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    try:
        row = await fetch_one(
            "INSERT INTO infra_categories (name) VALUES ($1) RETURNING name",
            name,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    return CategoryRow(**row)


@router.delete(
    "/{name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)]
)
async def delete_category(name: str):
    try:
        result = await execute("DELETE FROM infra_categories WHERE name = $1", name)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Impossible de supprimer la categorie '{name}' -- utilisee par des types",
        ) from exc
    if result.endswith(" 0"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Category '{name}' not found"
        )


# Actions attached to a category

@router.get(
    "/{category}/actions",
    response_model=list[CategoryActionRow],
    dependencies=[Depends(require_admin)],
)
async def list_category_actions(category: str):
    rows = await fetch_all(
        _ACTION_SELECT + " WHERE a.category = $1 ORDER BY a.name",
        category,
    )
    return [_action_row(r) for r in rows]


class CategoryActionCreate(BaseModel):
    name: str
    is_required: bool = False
    creates_named_type_id: UUID | None = None


class CategoryActionUpdate(BaseModel):
    is_required: bool | None = None
    creates_named_type_id: UUID | None = None


@router.post(
    "/{category}/actions",
    response_model=CategoryActionRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_category_action(category: str, payload: CategoryActionCreate):
    action_name = payload.name.strip()
    if not action_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
    cat = await fetch_one("SELECT name FROM infra_categories WHERE name = $1", category)
    if cat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category '{category}' not found",
        )
    try:
        row = await fetch_one(
            """INSERT INTO infra_category_actions (category, name, is_required, creates_named_type_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            category, action_name, payload.is_required, payload.creates_named_type_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    result = await fetch_one(_ACTION_SELECT + " WHERE a.id = $1", row["id"])
    assert result is not None
    return _action_row(result)


@router.patch(
    "/{category}/actions/{name}",
    response_model=CategoryActionRow,
    dependencies=[Depends(require_admin)],
)
async def update_category_action(category: str, name: str, payload: CategoryActionUpdate):
    sets = []
    params: list = [category, name]
    if payload.is_required is not None:
        params.append(payload.is_required)
        sets.append(f"is_required = ${len(params)}")
    if "creates_named_type_id" in payload.model_fields_set:
        params.append(payload.creates_named_type_id)
        sets.append(f"creates_named_type_id = ${len(params)}")
    if not sets:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="nothing to update")
    await execute(
        f"UPDATE infra_category_actions SET {', '.join(sets)} WHERE category = $1 AND name = $2",
        *params,
    )
    row = await fetch_one(_ACTION_SELECT + " WHERE a.category = $1 AND a.name = $2", category, name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{name}' not found in category '{category}'",
        )
    return _action_row(row)


@router.delete(
    "/{category}/actions/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_category_action(category: str, name: str):
    result = await execute(
        "DELETE FROM infra_category_actions WHERE category = $1 AND name = $2",
        category,
        name,
    )
    if result.endswith(" 0"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{name}' not found in category '{category}'",
        )
