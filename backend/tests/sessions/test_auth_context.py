from __future__ import annotations

from uuid import uuid4

from agflow.auth.context import AuthContext


def test_non_admin_context() -> None:
    key_id = uuid4()
    row = {"id": key_id, "scopes": ["read", "write"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.api_key_id == key_id
    assert ctx.is_admin is False


def test_admin_context() -> None:
    key_id = uuid4()
    row = {"id": key_id, "scopes": ["*"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.is_admin is True


def test_admin_also_with_other_scopes() -> None:
    row = {"id": uuid4(), "scopes": ["*", "write"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.is_admin is True
