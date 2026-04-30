from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.db import migrations
from agflow.db.migrations import _MIGRATIONS_LOCK_KEY, run_migrations


def _fake_pool_with_conn() -> tuple[MagicMock, AsyncMock]:
    """Return (pool, conn) where pool.acquire() yields conn via async context manager."""
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


@pytest.mark.asyncio
async def test_run_migrations_acquires_advisory_lock_when_available(tmp_path: Path) -> None:
    pool, conn = _fake_pool_with_conn()
    conn.fetchval.return_value = True  # pg_try_advisory_lock OK du 1er coup
    conn.fetch.return_value = []  # schema_migrations vide
    # tmp_path empty -> aucun fichier .sql -> rien a appliquer

    with (
        patch.object(migrations, "_ensure_bookkeeping_table", AsyncMock()),
        patch.object(migrations, "get_pool", AsyncMock(return_value=pool)),
    ):
        result = await run_migrations(tmp_path)

    assert result == []
    # Verifie que les 2 calls SQL critiques ont ete passes :
    # 1. pg_try_advisory_lock pour acquerir
    # 2. pg_advisory_unlock pour liberer
    sql_calls = [str(c.args[0]) for c in conn.fetchval.call_args_list + conn.execute.call_args_list]
    assert any("pg_try_advisory_lock" in s for s in sql_calls)
    assert any("pg_advisory_unlock" in s for s in sql_calls)
    # Le bloquant pg_advisory_lock NE doit PAS etre appele si try a reussi
    assert not any(
        "pg_advisory_lock(" in s and "try" not in s and "unlock" not in s for s in sql_calls
    ), "Blocking pg_advisory_lock should NOT be called when try_advisory_lock succeeded"


@pytest.mark.asyncio
async def test_run_migrations_waits_for_lock_when_held_by_other(tmp_path: Path) -> None:
    """Si pg_try_advisory_lock retourne False, on doit fallback sur le bloquant."""
    pool, conn = _fake_pool_with_conn()
    conn.fetchval.return_value = False  # pg_try_advisory_lock : autre replica detient le lock
    conn.fetch.return_value = []

    with (
        patch.object(migrations, "_ensure_bookkeeping_table", AsyncMock()),
        patch.object(migrations, "get_pool", AsyncMock(return_value=pool)),
    ):
        await run_migrations(tmp_path)

    # On doit avoir appele pg_advisory_lock bloquant en plus
    execute_calls = [str(c.args[0]) for c in conn.execute.call_args_list]
    blocking_lock_calls = [s for s in execute_calls if "pg_advisory_lock(" in s]
    assert len(blocking_lock_calls) >= 1, (
        "When pg_try_advisory_lock fails, the blocking pg_advisory_lock should be invoked"
    )


@pytest.mark.asyncio
async def test_run_migrations_releases_lock_even_if_apply_fails(tmp_path: Path) -> None:
    """Le finally doit toujours unlock, meme si _apply_pending leve."""
    pool, conn = _fake_pool_with_conn()
    conn.fetchval.return_value = True  # lock acquis du 1er coup

    failing_apply = AsyncMock(side_effect=RuntimeError("simulated migration failure"))

    with (
        patch.object(migrations, "_ensure_bookkeeping_table", AsyncMock()),
        patch.object(migrations, "get_pool", AsyncMock(return_value=pool)),
        patch.object(migrations, "_apply_pending", failing_apply),
        pytest.raises(RuntimeError, match="simulated migration failure"),
    ):
        await run_migrations(tmp_path)

    # Meme apres le crash, un pg_advisory_unlock doit avoir ete appele
    execute_calls = [str(c.args[0]) for c in conn.execute.call_args_list]
    assert any("pg_advisory_unlock" in s for s in execute_calls), (
        "pg_advisory_unlock must be called in finally even on failure"
    )


@pytest.mark.asyncio
async def test_lock_key_is_stable_int8() -> None:
    """Le lock key doit etre un int8 stable (deterministe entre runs)."""
    # Postgres int8 range : -2^63 .. 2^63 - 1
    assert isinstance(_MIGRATIONS_LOCK_KEY, int)
    assert -(2**63) <= _MIGRATIONS_LOCK_KEY < 2**63
    # Verifie qu'on retombe sur la meme valeur a un 2eme import
    import importlib

    from agflow.db import migrations as m_reload

    importlib.reload(m_reload)
    assert m_reload._MIGRATIONS_LOCK_KEY == _MIGRATIONS_LOCK_KEY
