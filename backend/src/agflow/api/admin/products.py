from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import ProductCreate, ProductDetail, ProductSummary
from agflow.services import product_catalog_service

router = APIRouter(
    prefix="/api/admin/products",
    tags=["admin-products"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ProductSummary])
async def list_products():
    return product_catalog_service.list_all()


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED)
async def create_product(payload: ProductCreate):
    try:
        return product_catalog_service.create(
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            category=payload.category,
            tags=payload.tags,
            recipe_yaml=payload.recipe_yaml,
        )
    except product_catalog_service.DuplicateProductError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(product_id: str):
    try:
        return product_catalog_service.get_by_id(product_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class RecipeUpdatePayload(BaseModel):
    recipe_yaml: str


@router.put("/{product_id}/recipe", response_model=ProductDetail)
async def update_recipe(product_id: str, payload: RecipeUpdatePayload):
    try:
        return product_catalog_service.update_recipe(product_id, payload.recipe_yaml)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: str):
    try:
        product_catalog_service.delete(product_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
