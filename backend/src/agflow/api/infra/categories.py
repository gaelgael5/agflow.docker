from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import CategoryActionRow, CategoryRow

router = APIRouter(prefix="/api/infra/categories", tags=["infra-categories"])


@router.get("", response_model=list[CategoryRow], dependencies=[Depends(require_admin)])
async def list_categories():
    rows = await fetch_all("SELECT name, is_vps FROM infra_categories ORDER BY name")
    return [CategoryRow(**r) for r in rows]


class CategoryCreate(BaseModel):
    name: str
    is_vps: bool = False


class CategoryUpdate(BaseModel):
    is_vps: bool


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
            "INSERT INTO infra_categories (name, is_vps) VALUES ($1, $2) RETURNING name, is_vps",
            name, payload.is_vps,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    return CategoryRow(**row)


@router.patch(
    "/{name}",
    response_model=CategoryRow,
    dependencies=[Depends(require_admin)],
)
async def update_category(name: str, payload: CategoryUpdate):
    row = await fetch_one(
        "UPDATE infra_categories SET is_vps = $2 WHERE name = $1 RETURNING name, is_vps",
        name, payload.is_vps,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Category '{name}' not found")
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
            detail=f"Impossible de supprimer la catégorie '{name}' — utilisée par des types",
        ) from exc
    if result.endswith(" 0"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Category '{name}' not found"
        )


# ── Actions attached to a category ──────────────────────────


@router.get(
    "/{category}/actions",
    response_model=list[CategoryActionRow],
    dependencies=[Depends(require_admin)],
)
async def list_category_actions(category: str):
    rows = await fetch_all(
        "SELECT id, name, is_required FROM infra_category_actions WHERE category = $1 ORDER BY name",
        category,
    )
    return [CategoryActionRow(**r) for r in rows]


class CategoryActionCreate(BaseModel):
    name: str
    is_required: bool = False


class CategoryActionUpdate(BaseModel):
    is_required: bool


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
            "INSERT INTO infra_category_actions (category, name, is_required) VALUES ($1, $2, $3) RETURNING id, name, is_required",
            category,
            action_name,
            payload.is_required,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assert row is not None
    return CategoryActionRow(**row)


@router.patch(
    "/{category}/actions/{name}",
    response_model=CategoryActionRow,
    dependencies=[Depends(require_admin)],
)
async def update_category_action(category: str, name: str, payload: CategoryActionUpdate):
    row = await fetch_one(
        "UPDATE infra_category_actions SET is_required = $3 WHERE category = $1 AND name = $2 RETURNING id, name, is_required",
        category, name, payload.is_required,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Action '{name}' not found in category '{category}'",
        )
    return CategoryActionRow(**row)


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
