"""AI Providers service — filesystem-based.

Config lives at {AGFLOW_DATA_DIR}/ai-providers.json.
Maps service types (image_generation, embedding, llm) to provider configs with secret refs.
"""
from __future__ import annotations

import json
import os
from typing import Any

import structlog

from agflow.schemas.ai_providers import ProviderSummary

_log = structlog.get_logger(__name__)


def _config_path() -> str:
    return os.path.join(os.environ.get("AGFLOW_DATA_DIR", "/app/data"), "ai-providers.json")


def _read_all() -> list[dict[str, Any]]:
    path = _config_path()
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.loads(f.read())
    return data if isinstance(data, list) else []


def _write_all(providers: list[dict[str, Any]]) -> None:
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(providers, indent=2, ensure_ascii=False))


def _to_summary(data: dict[str, Any]) -> ProviderSummary:
    return ProviderSummary(
        service_type=data.get("service_type", "image_generation"),
        provider_name=data.get("provider_name", ""),
        display_name=data.get("display_name", ""),
        secret_ref=data.get("secret_ref", ""),
        enabled=data.get("enabled", True),
        is_default=data.get("is_default", False),
    )


class ProviderNotFoundError(Exception):
    pass


class DuplicateProviderError(Exception):
    pass


def seed_defaults() -> None:
    """Create default provider configs if empty."""
    if _read_all():
        return
    defaults = [
        {
            "service_type": "image_generation",
            "provider_name": "dall-e-3",
            "display_name": "DALL-E 3 (OpenAI)",
            "secret_ref": "OPENAI_API_KEY",
            "enabled": True,
            "is_default": True,
        },
    ]
    _write_all(defaults)
    _log.info("ai_providers.seed_defaults")


def list_all() -> list[ProviderSummary]:
    return [_to_summary(p) for p in _read_all()]


def list_by_type(service_type: str) -> list[ProviderSummary]:
    return [_to_summary(p) for p in _read_all() if p.get("service_type") == service_type]


def get_default(service_type: str) -> ProviderSummary | None:
    for p in _read_all():
        if p.get("service_type") == service_type and p.get("is_default") and p.get("enabled"):
            return _to_summary(p)
    # Fallback: first enabled of this type
    for p in _read_all():
        if p.get("service_type") == service_type and p.get("enabled"):
            return _to_summary(p)
    return None


def create(
    service_type: str,
    provider_name: str,
    display_name: str,
    secret_ref: str = "",
    enabled: bool = True,
    is_default: bool = False,
) -> ProviderSummary:
    providers = _read_all()
    for p in providers:
        if p.get("service_type") == service_type and p.get("provider_name") == provider_name:
            raise DuplicateProviderError(f"Provider '{provider_name}' already exists for {service_type}")

    if is_default:
        for p in providers:
            if p.get("service_type") == service_type:
                p["is_default"] = False

    entry = {
        "service_type": service_type,
        "provider_name": provider_name,
        "display_name": display_name,
        "secret_ref": secret_ref,
        "enabled": enabled,
        "is_default": is_default,
    }
    providers.append(entry)
    _write_all(providers)
    _log.info("ai_providers.create", service_type=service_type, provider=provider_name)
    return _to_summary(entry)


def update(service_type: str, provider_name: str, **kwargs: Any) -> ProviderSummary:
    providers = _read_all()
    found = None
    for p in providers:
        if p.get("service_type") == service_type and p.get("provider_name") == provider_name:
            found = p
            break
    if found is None:
        raise ProviderNotFoundError(f"Provider '{provider_name}' not found for {service_type}")

    for k, v in kwargs.items():
        if v is not None:
            found[k] = v

    # If setting as default, unset others
    if kwargs.get("is_default"):
        for p in providers:
            if p is not found and p.get("service_type") == service_type:
                p["is_default"] = False

    _write_all(providers)
    _log.info("ai_providers.update", service_type=service_type, provider=provider_name)
    return _to_summary(found)


def delete(service_type: str, provider_name: str) -> None:
    providers = _read_all()
    new = [p for p in providers if not (p.get("service_type") == service_type and p.get("provider_name") == provider_name)]
    if len(new) == len(providers):
        raise ProviderNotFoundError(f"Provider '{provider_name}' not found for {service_type}")
    _write_all(new)
    _log.info("ai_providers.delete", service_type=service_type, provider=provider_name)


async def resolve_api_key(service_type: str, provider_name: str | None = None) -> str:
    """Resolve the API key for a provider from platform secrets."""
    from agflow.services import secrets_service

    if provider_name:
        providers = _read_all()
        for p in providers:
            if p.get("service_type") == service_type and p.get("provider_name") == provider_name:
                ref = p.get("secret_ref", "")
                if ref:
                    try:
                        resolved = await secrets_service.resolve_env([ref])
                        return resolved.get(ref, "")
                    except secrets_service.SecretNotFoundError:
                        return ""
                return ""

    default = get_default(service_type)
    if default and default.secret_ref:
        try:
            resolved = await secrets_service.resolve_env([default.secret_ref])
            return resolved.get(default.secret_ref, "")
        except secrets_service.SecretNotFoundError:
            return ""
    return ""
