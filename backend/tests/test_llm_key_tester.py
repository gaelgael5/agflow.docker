from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.services.llm_key_tester import check_key  # noqa: E402


class _FakeAsyncClient:
    """Drop-in fake for httpx.AsyncClient that returns a canned response."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return self._response


def _fake_client_factory(response: httpx.Response):
    def factory(*_args: object, **_kwargs: object) -> _FakeAsyncClient:
        return _FakeAsyncClient(response)

    return factory


@pytest.mark.asyncio
async def test_unknown_var_name_returns_unsupported() -> None:
    result = await check_key(var_name="RANDOM_TOKEN", value="xxx")
    assert result.supported is False
    assert result.ok is False


@pytest.mark.asyncio
async def test_anthropic_success() -> None:
    response = httpx.Response(status_code=200, json={"data": []})
    with patch(
        "agflow.services.llm_key_tester.httpx.AsyncClient",
        new=_fake_client_factory(response),
    ):
        result = await check_key(var_name="ANTHROPIC_API_KEY", value="sk-ant-valid")

    assert result.supported is True
    assert result.ok is True
    assert "200" in result.detail or "ok" in result.detail.lower()


@pytest.mark.asyncio
async def test_anthropic_unauthorized() -> None:
    response = httpx.Response(status_code=401, text="Unauthorized")
    with patch(
        "agflow.services.llm_key_tester.httpx.AsyncClient",
        new=_fake_client_factory(response),
    ):
        result = await check_key(var_name="ANTHROPIC_API_KEY", value="sk-ant-bad")

    assert result.supported is True
    assert result.ok is False
    assert "401" in result.detail
