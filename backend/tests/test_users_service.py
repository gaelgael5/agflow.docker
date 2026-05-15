from __future__ import annotations

import os

import pytest

os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
os.environ.setdefault("API_KEY_SALT", "test-salt-for-hmac-32chars-ok!!")


from agflow.services import users_service
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield


@pytest.mark.asyncio
async def test_create_user() -> None:
    user = await users_service.create(email="alice@example.com", name="Alice")
    assert user.email == "alice@example.com"
    assert user.name == "Alice"
    assert user.status == "active"
    assert user.role == "user"
    assert user.api_key_count == 0


@pytest.mark.asyncio
async def test_seed_admin() -> None:
    await users_service.seed_admin("admin@example.com")
    user = await users_service.get_by_email("admin@example.com")
    assert user is not None
    assert user.role == "admin"
    assert user.status == "active"


@pytest.mark.asyncio
async def test_seed_admin_idempotent() -> None:
    await users_service.seed_admin("admin@example.com")
    await users_service.seed_admin("admin@example.com")
    all_users = await users_service.list_all()
    admins = [u for u in all_users if u.email == "admin@example.com"]
    assert len(admins) == 1


@pytest.mark.asyncio
async def test_approve_user() -> None:
    pending = await users_service.create(
        email="pending@example.com", status="pending"
    )
    assert pending.status == "pending"
    assert pending.approved_at is None

    # create an admin to approve
    admin = await users_service.create(email="admin@example.com", role="admin")
    approved = await users_service.approve(pending.id, approved_by=admin.id)
    assert approved.status == "active"
    assert approved.approved_at is not None


@pytest.mark.asyncio
async def test_disable_and_enable() -> None:
    user = await users_service.create(email="bob@example.com")
    assert user.status == "active"

    disabled = await users_service.disable(user.id)
    assert disabled.status == "disabled"

    enabled = await users_service.enable(user.id)
    assert enabled.status == "active"


@pytest.mark.asyncio
async def test_update_scopes() -> None:
    user = await users_service.create(email="carol@example.com")
    assert user.scopes == []

    updated = await users_service.update(user.id, scopes=["read:agents", "write:agents"])
    assert set(updated.scopes) == {"read:agents", "write:agents"}


@pytest.mark.asyncio
async def test_delete_user() -> None:
    user = await users_service.create(email="dave@example.com")
    await users_service.delete(user.id)

    with pytest.raises(users_service.UserNotFoundError):
        await users_service.get_by_id(user.id)
