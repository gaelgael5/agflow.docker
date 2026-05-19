"""Generic docker exec helper used by services that need to run commands inside containers."""
from __future__ import annotations

import aiodocker


async def docker_exec(container_name: str, cmd: list[str]) -> tuple[int, str, str]:
    """Run a command in a named docker container and capture (exit_code, stdout, stderr).

    The container must already be running. Streams are decoded as UTF-8 with `replace`
    so binary output doesn't crash the caller.
    """
    docker = aiodocker.Docker()
    try:
        container = await docker.containers.get(container_name)
        exec_obj = await container.exec(cmd=cmd, stdout=True, stderr=True)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        async with exec_obj.start(detach=False) as stream:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                if msg.stream == 1:
                    stdout_chunks.append(msg.data)
                else:
                    stderr_chunks.append(msg.data)
        info = await exec_obj.inspect()
        return (
            int(info.get("ExitCode") or 0),
            b"".join(stdout_chunks).decode("utf-8", errors="replace"),
            b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        )
    finally:
        await docker.close()
