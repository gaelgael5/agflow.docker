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


@router.get("/{product_id}/variables")
async def get_product_variables(product_id: str):
    """Return the required variables and secrets for a product."""
    import re

    try:
        detail = product_catalog_service.get_by_id(product_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    recipe = detail.recipe
    recipe_yaml = detail.recipe_yaml

    # Declared names
    declared_vars = {v.get("name", "") for v in recipe.get("variables", [])}
    declared_secrets = {s.get("name", "") for s in recipe.get("secrets_required", [])}
    # Built-in computed names
    builtin = {"_name", "instance_name", "instance_id", "service_url"}
    for svc in recipe.get("services", []):
        svc_id = svc.get("id", "")
        if svc_id:
            builtin.add(f"services.{svc_id}.host")
            builtin.add(f"services.{svc_id}.port")

    # Strip comments before scanning for variable references
    yaml_no_comments = "\n".join(
        line for line in recipe_yaml.splitlines()
        if not line.lstrip().startswith("#")
    )

    # Scan YAML for all {{ }} and ${} references
    all_jinja = set(re.findall(r"\{\{\s*([^}]+?)\s*\}\}", yaml_no_comments))
    all_env = set(re.findall(r"\$\{([^}]+)\}", yaml_no_comments))

    # Detect shared dependencies: {{ shared.X.Y }}
    shared_deps: list[dict] = []
    shared_names: set[str] = set()
    for ref in all_jinja:
        m = re.match(r"shared\.(\w+)\.(\w+)", ref)
        if m:
            dep_name = m.group(1)
            dep_prop = m.group(2)
            if dep_name not in shared_names:
                shared_names.add(dep_name)
                shared_deps.append({
                    "name": dep_name,
                    "property": dep_prop,
                    "syntax": "{{ shared." + dep_name + "." + dep_prop + " }}",
                })

    # Find undeclared {{ }} variables (not in variables, not builtin, not shared, not nested {{_name}})
    undeclared_vars: list[dict] = []
    for ref in all_jinja:
        ref_clean = ref.strip()
        if ref_clean in declared_vars or ref_clean in builtin:
            continue
        if ref_clean.startswith("shared."):
            continue
        if "{{" in ref_clean:  # nested template like services.{{_name}}-redis.host
            continue
        undeclared_vars.append({
            "name": ref_clean,
            "description": "",
            "type": "variable",
            "syntax": "{{ " + ref_clean + " }}",
            "required": True,
            "default": "",
            "undeclared": True,
        })

    # Find undeclared ${} secrets
    undeclared_secrets: list[dict] = []
    for ref in all_env:
        if ref not in declared_secrets:
            undeclared_secrets.append({
                "name": ref,
                "description": "",
                "type": "secret",
                "syntax": "${" + ref + "}",
                "required": True,
                "default": "",
                "undeclared": True,
            })

    variables = []
    for v in recipe.get("variables", []):
        variables.append({
            "name": v.get("name", ""),
            "description": v.get("description", ""),
            "type": "variable",
            "syntax": "{{ " + v.get("name", "") + " }}",
            "required": v.get("required", False),
            "default": v.get("default", ""),
        })
    # Append undeclared variables
    variables.extend(undeclared_vars)

    for s in recipe.get("secrets_required", []):
        variables.append({
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "type": "secret",
            "syntax": "${" + s.get("name", "") + "}",
            "required": True,
            "default": "",
            "generate": s.get("generate"),
        })
    # Append undeclared secrets
    secrets_list = [v for v in variables if v.get("type") == "secret"]
    variables.extend(undeclared_secrets)

    # Connectors
    connectors = []
    for c in recipe.get("connectors", []):
        connectors.append({
            "name": c.get("name", ""),
            "description": c.get("description", ""),
            "package": c.get("package", ""),
            "runtime": c.get("runtime", ""),
            "transport": c.get("transport", ""),
            "status": c.get("status", ""),
            "env": c.get("env", {}),
        })

    # Computed variables (from services paths like services.app.host)
    computed = []
    for svc in recipe.get("services", []):
        svc_id = svc.get("id", "")
        if svc_id:
            computed.append({
                "path": f"services.{svc_id}.host",
                "description": f"Hostname du service {svc_id} (résolu au déploiement)",
            })
            for port in svc.get("ports", []):
                computed.append({
                    "path": f"services.{svc_id}.port",
                    "description": f"Port {port} du service {svc_id}",
                })

    # API definition
    api_def = recipe.get("api")
    api_info = None
    if api_def and isinstance(api_def, dict):
        api_info = {
            "source": api_def.get("source", ""),
            "url": api_def.get("url", ""),
            "base_url": api_def.get("base_url", ""),
            "auth_header": api_def.get("auth_header", ""),
            "auth_prefix": api_def.get("auth_prefix", ""),
            "auth_secret_ref": api_def.get("auth_secret_ref", ""),
        }

    # Services (exposed)
    services = []
    for svc in recipe.get("services", []):
        services.append({
            "id": svc.get("id", ""),
            "image": svc.get("image", ""),
            "ports": svc.get("ports", []),
            "requires_services": svc.get("requires_services", []),
        })

    return {
        "product_id": product_id,
        "variables": variables,
        "connectors": connectors,
        "computed": computed,
        "api": api_info,
        "services": services,
        "shared_deps": shared_deps,
    }


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: str):
    try:
        product_catalog_service.delete(product_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
