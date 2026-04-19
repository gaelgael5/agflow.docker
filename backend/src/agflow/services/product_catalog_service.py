"""Product catalog service — reads YAML recipes from disk.

Recipes live at {AGFLOW_DATA_DIR}/products/{id}.yaml (or fallback to
the bundled data/products/ in the source tree).
Read-only in V1 — no CRUD UI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
import yaml

from agflow.schemas.products import ProductDetail, ProductSummary

_log = structlog.get_logger(__name__)


class ProductNotFoundError(Exception):
    pass


def _products_dir() -> Path:
    """Data dir products, fallback to bundled."""
    data = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    data_path = Path(data) / "products"
    if data_path.is_dir():
        return data_path
    # Fallback: bundled in source
    return Path(__file__).parent.parent.parent.parent / "data" / "products"


def _load_recipe(yaml_path: Path) -> dict[str, Any] | None:
    try:
        with open(yaml_path, encoding="utf-8") as f:
            recipe = yaml.safe_load(f.read())
        if isinstance(recipe, dict) and "id" in recipe:
            return recipe
    except Exception:
        pass
    return None


def _to_summary(recipe: dict[str, Any]) -> ProductSummary:
    return ProductSummary(
        id=recipe["id"],
        display_name=recipe.get("display_name", recipe["id"]),
        description=recipe.get("description", ""),
        category=recipe.get("category", "other"),
        tags=recipe.get("tags", []),
        min_ram_mb=recipe.get("min_ram_mb", 512),
        config_only=recipe.get("config_only", False),
        has_openapi="openapi" in recipe,
        mcp_package_id=recipe.get("mcp_package_id"),
        recipe_version=recipe.get("recipe_version", "1.0.0"),
    )


def list_all() -> list[ProductSummary]:
    d = _products_dir()
    if not d.is_dir():
        return []
    results = []
    for p in sorted(d.glob("*.yaml")):
        recipe = _load_recipe(p)
        if recipe:
            results.append(_to_summary(recipe))
    return results


def get_by_id(product_id: str) -> ProductDetail:
    d = _products_dir()
    yaml_path = d / f"{product_id}.yaml"
    if not yaml_path.is_file():
        raise ProductNotFoundError(f"Product '{product_id}' not found")
    recipe = _load_recipe(yaml_path)
    if recipe is None:
        raise ProductNotFoundError(f"Invalid recipe for '{product_id}'")
    summary = _to_summary(recipe)
    return ProductDetail(**summary.model_dump(), recipe=recipe)
