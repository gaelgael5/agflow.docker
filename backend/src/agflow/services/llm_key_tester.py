from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import structlog

from agflow.schemas.secrets import SecretTestResult

_log = structlog.get_logger(__name__)
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def check_key(var_name: str, value: str) -> SecretTestResult:
    """Probe a provider's API to validate a key."""
    probe = _PROBES.get(var_name)
    if probe is None:
        return SecretTestResult(
            supported=False,
            ok=False,
            detail=f"No test probe implemented for {var_name}",
        )
    return await probe(value)


async def _probe_anthropic(key: str) -> SecretTestResult:
    url = "https://api.anthropic.com/v1/models"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        _log.warning("llm_key_tester.anthropic.error", error=str(exc))
        return SecretTestResult(
            supported=True, ok=False, detail=f"Connection error: {exc}"
        )
    if response.status_code == 200:
        return SecretTestResult(supported=True, ok=True, detail="200 ok")
    return SecretTestResult(
        supported=True,
        ok=False,
        detail=f"HTTP {response.status_code}: {response.text[:200]}",
    )


async def _probe_openai(key: str) -> SecretTestResult:
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return SecretTestResult(
            supported=True, ok=False, detail=f"Connection error: {exc}"
        )
    if response.status_code == 200:
        return SecretTestResult(supported=True, ok=True, detail="200 ok")
    return SecretTestResult(
        supported=True,
        ok=False,
        detail=f"HTTP {response.status_code}: {response.text[:200]}",
    )


_PROBES: dict[str, Callable[[str], Awaitable[SecretTestResult]]] = {
    "ANTHROPIC_API_KEY": _probe_anthropic,
    "OPENAI_API_KEY": _probe_openai,
}
