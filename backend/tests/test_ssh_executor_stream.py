import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_exec_command_stream_yields_lines():
    """exec_command_stream doit produire des tuples (stream_type, line)."""
    from agflow.services.ssh_executor import exec_command_stream

    lines_received = []

    # Simuler une connexion asyncssh qui retourne deux lignes stdout
    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.write_eof = MagicMock()
    mock_process.exit_status = 0

    async def mock_stdout_iter():
        for line in ["line1\n", "line2\n"]:
            yield line

    mock_process.stdout = mock_stdout_iter()

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_proc_ctx = MagicMock()
    mock_proc_ctx.__aenter__ = AsyncMock(return_value=mock_process)
    mock_proc_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.create_process = MagicMock(return_value=mock_proc_ctx)

    with patch("agflow.services.ssh_executor._connect", new_callable=AsyncMock, return_value=mock_conn):
        async for stream_type, line in exec_command_stream(
            host="h", port=22, username="u", password="p",
            private_key=None, passphrase=None, command="echo test",
        ):
            lines_received.append((stream_type, line))

    assert ("stdout", "line1") in lines_received
    assert ("stdout", "line2") in lines_received
