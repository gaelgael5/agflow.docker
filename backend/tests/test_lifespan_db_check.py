from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from agflow.main import _check_db_connectivity


def _make_pool_with_fetchval_error(error: BaseException) -> MagicMock:
    """Construit un pool mocké dont conn.fetchval lève l'erreur fournie."""
    fake_pool = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.fetchval.side_effect = error
    fake_pool.acquire.return_value.__aenter__.return_value = fake_conn
    fake_pool.acquire.return_value.__aexit__.return_value = None
    return fake_pool


@pytest.mark.asyncio
async def test_check_db_connectivity_raises_on_missing_database():
    """Si la DB n'existe pas, _check_db_connectivity loggue db.missing_database et relance."""
    fake_pool = _make_pool_with_fetchval_error(
        asyncpg.InvalidCatalogNameError('database "agflow_docker" does not exist')
    )
    log = MagicMock()

    with (
        patch("agflow.db.pool.get_pool", AsyncMock(return_value=fake_pool)),
        pytest.raises(asyncpg.InvalidCatalogNameError),
    ):
        await _check_db_connectivity(log)

    log.error.assert_called_once()
    call_args = log.error.call_args
    assert call_args.args[0] == "db.missing_database"
    assert "install.sh --setup-db" in call_args.kwargs["message"]
    assert call_args.kwargs["dsn_database"] == "agflow_docker"


@pytest.mark.asyncio
async def test_check_db_connectivity_raises_on_invalid_password():
    """Si l'auth échoue (password), loggue db.auth_failed et relance."""
    fake_pool = _make_pool_with_fetchval_error(
        asyncpg.InvalidPasswordError("password authentication failed")
    )
    log = MagicMock()

    with (
        patch("agflow.db.pool.get_pool", AsyncMock(return_value=fake_pool)),
        pytest.raises(asyncpg.InvalidPasswordError),
    ):
        await _check_db_connectivity(log)

    log.error.assert_called_once()
    call_args = log.error.call_args
    assert call_args.args[0] == "db.auth_failed"
    assert "database_url" in call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_check_db_connectivity_raises_on_invalid_authorization():
    """Si l'auth échoue (autorisation), loggue db.auth_failed et relance."""
    fake_pool = _make_pool_with_fetchval_error(
        asyncpg.InvalidAuthorizationSpecificationError("authorization refused")
    )
    log = MagicMock()

    with (
        patch("agflow.db.pool.get_pool", AsyncMock(return_value=fake_pool)),
        pytest.raises(asyncpg.InvalidAuthorizationSpecificationError),
    ):
        await _check_db_connectivity(log)

    log.error.assert_called_once()
    assert log.error.call_args.args[0] == "db.auth_failed"


@pytest.mark.asyncio
async def test_check_db_connectivity_raises_on_unreachable_server():
    """Si le serveur Postgres est injoignable, loggue db.unreachable et relance."""
    fake_pool = _make_pool_with_fetchval_error(
        OSError("Connection refused: [Errno 111]")
    )
    log = MagicMock()

    with (
        patch("agflow.db.pool.get_pool", AsyncMock(return_value=fake_pool)),
        pytest.raises(OSError),
    ):
        await _check_db_connectivity(log)

    log.error.assert_called_once()
    call_args = log.error.call_args
    assert call_args.args[0] == "db.unreachable"
    assert "host:port" in call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_check_db_connectivity_logs_ok_when_db_reachable():
    """Si la DB répond correctement, loggue db.connectivity_ok et ne lève rien."""
    fake_pool = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.fetchval.return_value = 1
    fake_pool.acquire.return_value.__aenter__.return_value = fake_conn
    fake_pool.acquire.return_value.__aexit__.return_value = None
    log = MagicMock()

    with patch("agflow.db.pool.get_pool", AsyncMock(return_value=fake_pool)):
        await _check_db_connectivity(log)

    log.info.assert_called_once_with("db.connectivity_ok")
    log.error.assert_not_called()
