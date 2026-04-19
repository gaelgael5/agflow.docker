"""SSH executor — wrapper around asyncssh.

Provides connect + exec helpers for servers and machines.
"""
from __future__ import annotations

from typing import Any

import asyncssh
import structlog

_log = structlog.get_logger(__name__)


class SSHConnectionError(Exception):
    pass


async def test_connection(
    host: str,
    port: int = 22,
    username: str | None = None,
    password: str | None = None,
    private_key: str | None = None,
    passphrase: str | None = None,
) -> dict[str, Any]:
    """Test SSH connectivity. Returns {success, message}."""
    try:
        conn = await _connect(host, port, username, password, private_key, passphrase)
        async with conn:
            result = await conn.run("echo ok", check=True)
            return {"success": True, "message": f"Connected — {result.stdout.strip()}"}
    except Exception as exc:
        _log.warning("ssh.test_failed", host=host, port=port, error=str(exc))
        return {"success": False, "message": str(exc)}


async def exec_command(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    private_key: str | None,
    passphrase: str | None,
    command: str,
) -> dict[str, Any]:
    """Execute a command via SSH. Returns {exit_code, stdout, stderr}."""
    try:
        conn = await _connect(host, port, username, password, private_key, passphrase)
        async with conn:
            result = await conn.run(command, check=False)
            return {
                "exit_code": result.exit_status,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
            }
    except Exception as exc:
        raise SSHConnectionError(str(exc)) from exc


async def _connect(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    private_key: str | None,
    passphrase: str | None,
) -> asyncssh.SSHClientConnection:
    """Build an asyncssh connection with the provided credentials."""
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "known_hosts": None,  # Skip host key verification in V1
    }
    if username:
        kwargs["username"] = username
    if password:
        kwargs["password"] = password
    if private_key:
        key = asyncssh.import_private_key(private_key, passphrase)
        kwargs["client_keys"] = [key]

    return await asyncssh.connect(**kwargs)
