"""SSH executor — wrapper around asyncssh.

Provides connect + exec helpers for servers and machines.
"""
from __future__ import annotations

import asyncio
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
    connect_timeout: float = 10.0,
) -> dict[str, Any]:
    """Test SSH connectivity. Returns {success, message}.

    `connect_timeout` borne le temps total de la phase de connexion (TCP + SSH
    handshake) pour éviter un blocage de 2 min sur l'OS-level timeout quand
    le host est injoignable (typo dans l'IP, machine éteinte, etc.).
    """
    try:
        conn = await asyncio.wait_for(
            _connect(host, port, username, password, private_key, passphrase),
            timeout=connect_timeout,
        )
        async with conn:
            result = await conn.run("echo ok", check=True)
            return {"success": True, "message": f"Connected — {result.stdout.strip()}"}
    except TimeoutError:
        msg = f"Connection timed out after {connect_timeout:.0f}s"
        _log.warning("ssh.test_timeout", host=host, port=port, timeout=connect_timeout)
        return {"success": False, "message": msg}
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
    input: str | None = None,
) -> dict[str, Any]:
    """Execute a command via SSH. Returns {exit_code, stdout, stderr}.

    `input` is piped to the remote command's stdin — utile pour ecrire
    un fichier via `cat > path` sans avoir a juggler avec un heredoc.
    """
    try:
        conn = await _connect(host, port, username, password, private_key, passphrase)
        async with conn:
            result = await conn.run(command, check=False, input=input)
            return {
                "exit_code": result.exit_status,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
            }
    except Exception as exc:
        raise SSHConnectionError(str(exc)) from exc


async def exec_command_stream(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    private_key: str | None,
    passphrase: str | None,
    command: str,
    input: str | None = None,
):
    """Execute a command via SSH, yielding (stream_type, line) tuples.

    stream_type is 'stdout', 'stderr', or 'exit' (last tuple carries exit code as str).
    """
    conn = await _connect(host, port, username, password, private_key, passphrase)
    async with conn, conn.create_process(command) as proc:
        if input is not None:
            proc.stdin.write(input)
            proc.stdin.write_eof()
        async for raw_line in proc.stdout:
            yield "stdout", raw_line.rstrip("\n")
        async for raw_line in proc.stderr:
            yield "stderr", raw_line.rstrip("\n")
        exit_code = proc.exit_status if proc.exit_status is not None else -1
        yield "exit", str(exit_code)


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
