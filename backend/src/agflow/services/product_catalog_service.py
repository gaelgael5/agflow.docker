"""Product catalog service — filesystem-based.

Each product is a YAML file at {AGFLOW_DATA_DIR}/products/{slug}.yaml.
All properties (id, display_name, description, category, etc.) are read
directly from the YAML content. No separate metadata file.
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


class DuplicateProductError(Exception):
    pass


def _products_dir() -> Path:
    data = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    data_path = Path(data) / "products"
    if data_path.is_dir():
        return data_path
    return Path(__file__).parent.parent.parent.parent / "data" / "products"


def _product_path(slug: str) -> Path:
    return _products_dir() / f"{slug}.yaml"


def _load(slug: str) -> tuple[dict[str, Any], str] | None:
    path = _product_path(slug)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    recipe = yaml.safe_load(raw)
    if not isinstance(recipe, dict):
        return None
    recipe.setdefault("id", slug)
    return recipe, raw


def _to_summary(recipe: dict[str, Any]) -> ProductSummary:
    return ProductSummary(
        id=recipe.get("id", ""),
        display_name=recipe.get("display_name", recipe.get("id", "")),
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
        result = _load(p.stem)
        if result:
            results.append(_to_summary(result[0]))
    return results


def get_by_id(product_id: str) -> ProductDetail:
    result = _load(product_id)
    if result is None:
        raise ProductNotFoundError(f"Product '{product_id}' not found")
    recipe, raw = result
    return ProductDetail(**_to_summary(recipe).model_dump(), recipe=recipe, recipe_yaml=raw)


def create(
    slug: str,
    display_name: str,
    description: str = "",
    category: str = "other",
    tags: list[str] | None = None,
    recipe_yaml: str = "",
) -> ProductSummary:
    if _product_path(slug).is_file():
        raise DuplicateProductError(f"Product '{slug}' already exists")

    os.makedirs(_products_dir(), exist_ok=True)

    if not recipe_yaml.strip():
        recipe_yaml = f"""id: {slug}
display_name: "{display_name}"
description: "{description}"
category: {category}
tags: {tags or []}
config_only: true

secrets_required: []
variables: []
"""

    with open(_product_path(slug), "w", encoding="utf-8") as f:
        f.write(recipe_yaml)

    _log.info("product_catalog.create", slug=slug)
    result = _load(slug)
    assert result is not None
    return _to_summary(result[0])


def update_recipe(slug: str, recipe_yaml: str) -> ProductDetail:
    if not _product_path(slug).is_file():
        raise ProductNotFoundError(f"Product '{slug}' not found")

    with open(_product_path(slug), "w", encoding="utf-8") as f:
        f.write(recipe_yaml)

    _log.info("product_catalog.update_recipe", slug=slug)
    return get_by_id(slug)


def get_recipe_raw(slug: str) -> str:
    result = _load(slug)
    if result is None:
        raise ProductNotFoundError(f"Product '{slug}' not found")
    return result[1]


def delete(slug: str) -> None:
    path = _product_path(slug)
    if not path.is_file():
        raise ProductNotFoundError(f"Product '{slug}' not found")
    os.remove(path)
    _log.info("product_catalog.delete", slug=slug)
