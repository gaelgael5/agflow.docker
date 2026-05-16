from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
os.environ.setdefault("API_KEY_SALT", "test-salt-for-hmac-32chars-ok!!")


from agflow.services import api_keys_service, users_service
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    await users_service.create(email="admin@test.com", role="admin", status="active")
    yield


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    admin = await users_service.get_by_email("admin@test.com")
    assert admin is not None

    expires_at = api_keys_service.compute_expiry("12m")
    created = await api_keys_service.create(
        name="my-key",
        scopes=["agents:read"],
        rate_limit=120,
        expires_at=expires_at,
        owner_id=admin.id,
    )

    assert created.full_key.startswith("agfd_")
    assert len(created.full_key) == 53  # "agfd_" (5) + 48 hex chars
    assert created.prefix == created.full_key[5:17]  # 12 hex chars after prefix

    keys = await api_keys_service.list_all(owner_id=admin.id)
    assert len(keys) == 1
    assert keys[0].name == "my-key"
    assert keys[0].revoked is False


@pytest.mark.asyncio
async def test_revoke_key() -> None:
    admin = await users_service.get_by_email("admin@test.com")
    assert admin is not None

    created = await api_keys_service.create(
        name="revoke-me",
        scopes=[],
        rate_limit=60,
        expires_at=None,
        owner_id=admin.id,
    )

    await api_keys_service.revoke(created.id)

    key = await api_keys_service.get_by_id(created.id)
    assert key.revoked is True


@pytest.mark.asyncio
async def test_validate_key_scopes_admin() -> None:
    rejected = api_keys_service.validate_key_scopes(
        user_role="admin",
        user_scopes=[],
        requested_scopes=["*", "secrets:write", "users:manage"],
    )
    assert rejected == []


@pytest.mark.asyncio
async def test_validate_key_scopes_user() -> None:
    rejected = api_keys_service.validate_key_scopes(
        user_role="user",
        user_scopes=["agents:read", "agents:run"],
        requested_scopes=["agents:read", "agents:write"],
    )
    assert rejected == ["agents:write"]


@pytest.mark.asyncio
async def test_keys_manage_always_implicit() -> None:
    rejected = api_keys_service.validate_key_scopes(
        user_role="user",
        user_scopes=["agents:read"],
        requested_scopes=["keys:manage"],
    )
    assert rejected == []
