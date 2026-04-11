from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow"
os.environ["SECRETS_MASTER_KEY"] = "test-master-key-phrase-32chars-ok"

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute, fetch_one  # noqa: E402
from agflow.services import secrets_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean_secrets_table():
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_secret_encrypts_value() -> None:
    summary = await secrets_service.create(var_name="ANTHROPIC_API_KEY", value="sk-ant-xyz")

    assert summary.var_name == "ANTHROPIC_API_KEY"
    assert summary.scope == "global"
    assert summary.id is not None

    row = await fetch_one("SELECT value_encrypted FROM secrets WHERE id = $1", summary.id)
    assert row is not None
    assert b"sk-ant-xyz" not in row["value_encrypted"]


@pytest.mark.asyncio
async def test_reveal_decrypts_value() -> None:
    summary = await secrets_service.create(var_name="OPENAI_API_KEY", value="sk-openai-abc")

    revealed = await secrets_service.reveal(summary.id)
    assert revealed.value == "sk-openai-abc"
    assert revealed.var_name == "OPENAI_API_KEY"


@pytest.mark.asyncio
async def test_list_returns_summaries_without_values() -> None:
    await secrets_service.create(var_name="KEY_A", value="value-a")
    await secrets_service.create(var_name="KEY_B", value="value-b")

    items = await secrets_service.list_all()
    names = [s.var_name for s in items]
    assert "KEY_A" in names
    assert "KEY_B" in names

    for item in items:
        assert not hasattr(item, "value")


@pytest.mark.asyncio
async def test_update_replaces_value() -> None:
    summary = await secrets_service.create(var_name="KEY_UPDATE", value="old")

    await secrets_service.update(summary.id, value="new")

    revealed = await secrets_service.reveal(summary.id)
    assert revealed.value == "new"


@pytest.mark.asyncio
async def test_delete_removes_the_row() -> None:
    summary = await secrets_service.create(var_name="KEY_DEL", value="x")

    await secrets_service.delete(summary.id)

    items = await secrets_service.list_all()
    assert all(s.id != summary.id for s in items)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_var_name_in_same_scope() -> None:
    await secrets_service.create(var_name="DUPKEY", value="a")

    with pytest.raises(secrets_service.DuplicateSecretError):
        await secrets_service.create(var_name="DUPKEY", value="b")


@pytest.mark.asyncio
async def test_reveal_missing_raises() -> None:
    with pytest.raises(secrets_service.SecretNotFoundError):
        await secrets_service.reveal(uuid.uuid4())


@pytest.mark.asyncio
async def test_resolve_env_returns_dict() -> None:
    await secrets_service.create(var_name="ANTHROPIC_API_KEY", value="sk-ant")
    await secrets_service.create(var_name="OPENAI_API_KEY", value="sk-openai")

    env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
    assert env == {"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-openai"}


@pytest.mark.asyncio
async def test_resolve_env_raises_on_missing() -> None:
    with pytest.raises(secrets_service.SecretNotFoundError) as exc:
        await secrets_service.resolve_env(["MISSING_KEY"])
    assert "MISSING_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_status_returns_per_var() -> None:
    await secrets_service.create(var_name="KEY_OK", value="value")
    await secrets_service.create(var_name="KEY_EMPTY", value=" ")

    status = await secrets_service.resolve_status(["KEY_OK", "KEY_EMPTY", "KEY_MISSING"])
    assert status["KEY_OK"] == "ok"
    assert status["KEY_EMPTY"] == "empty"
    assert status["KEY_MISSING"] == "missing"
