from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.products import ProductDetail, ProductSummary
from agflow.services import product_catalog_service

router = APIRouter(
    prefix="/api/admin/products",
    tags=["admin-products"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ProductSummary])
async def list_products():
    return product_catalog_service.list_all()


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(product_id: str):
    try:
        return product_catalog_service.get_by_id(product_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
