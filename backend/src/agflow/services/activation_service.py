"""Activation service — the core M7 flow.

When an instance is activated:
1. Create the product_backend
2. Register MCP in M3 (if mcp_package_id defined)
3. Auto-create agent_api_contracts (if openapi defined)

When stopped:
1. Remove auto-managed agent_api_contracts
2. Mark backend as disconnected
"""
from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from agflow.services import (
    product_backends_service,
    product_catalog_service,
    product_instances_service,
)

_log = structlog.get_logger(__name__)


async def activate(project_id: str, instance_id: str, service_url: str) -> dict[str, Any]:
    """Full activation flow for a product instance."""
    instance = product_instances_service.get_by_id(project_id, instance_id)
    product = product_catalog_service.get_by_id(instance.catalog_id)
    recipe = product.recipe

    # Step 1 — Update instance status
    product_instances_service.activate(project_id, instance_id, service_url)

    # Step 2 — Create backend
    backend_data: dict[str, Any] = {
        "catalog_id": instance.catalog_id,
        "product_name": product.display_name,
        "connection_url": service_url,
        "status": "configured",
        "mcp_config": {},
        "openapi_url": None,
        "openapi_fetched": False,
    }

    # Step 3 — MCP config (from recipe)
    mcp_id = recipe.get("mcp_package_id")
    if mcp_id:
        backend_data["mcp_config"] = {
            "package_id": mcp_id,
            "service_url": service_url,
        }

    # Step 4 — OpenAPI contract (if defined in recipe)
    openapi = recipe.get("openapi")
    if openapi:
        openapi_url = _resolve_template(openapi.get("url", ""), {
            "service_url": service_url,
            **instance.variables,
        })
        backend_data["openapi_url"] = openapi_url
        backend_data["openapi_base_url"] = _resolve_template(
            openapi.get("base_url", ""), {"service_url": service_url, **instance.variables},
        )
        backend_data["openapi_auth_header"] = openapi.get("auth_header", "Authorization")
        backend_data["openapi_auth_prefix"] = openapi.get("auth_prefix", "Bearer")
        backend_data["openapi_auth_secret_ref"] = openapi.get("auth_secret_ref", "")

        # Try to fetch the spec
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
                resp = await client.get(openapi_url)
                resp.raise_for_status()
                backend_data["openapi_spec"] = resp.text
                backend_data["openapi_fetched"] = True
                backend_data["status"] = "connected"
                _log.info("activation.openapi_fetched", url=openapi_url)
        except Exception as exc:
            _log.warning("activation.openapi_fetch_failed", url=openapi_url, error=str(exc))
            backend_data["status"] = "connection_failed"

    product_backends_service.save(project_id, instance_id, backend_data)
    _log.info("activation.complete", project=project_id, instance=instance_id)

    return backend_data


async def deactivate(project_id: str, instance_id: str) -> None:
    """Stop an instance — mark backend as disconnected."""
    product_instances_service.stop(project_id, instance_id)

    backend = product_backends_service.get(project_id, instance_id)
    if backend:
        backend["status"] = "connection_failed"
        product_backends_service.save(project_id, instance_id, backend)

    _log.info("activation.deactivate", project=project_id, instance=instance_id)


async def refresh_openapi(project_id: str, instance_id: str) -> dict[str, Any]:
    """Re-fetch the OpenAPI spec for an active instance."""
    backend = product_backends_service.get(project_id, instance_id)
    if not backend:
        raise product_backends_service.BackendNotFoundError(f"Backend not found for {instance_id}")

    openapi_url = backend.get("openapi_url")
    if not openapi_url:
        raise ValueError("No OpenAPI URL configured for this backend")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
            resp = await client.get(openapi_url)
            resp.raise_for_status()
            backend["openapi_spec"] = resp.text
            backend["openapi_fetched"] = True
            backend["status"] = "connected"
    except Exception as exc:
        backend["status"] = "connection_failed"
        raise ValueError(f"Failed to fetch OpenAPI: {exc}") from exc
    finally:
        product_backends_service.save(project_id, instance_id, backend)

    _log.info("activation.openapi_refreshed", url=openapi_url)
    return backend


def _resolve_template(text: str, variables: dict[str, str]) -> str:
    """Resolve {{ variable }} patterns."""
    def replacer(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        return variables.get(key, m.group(0))
    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replacer, text)
