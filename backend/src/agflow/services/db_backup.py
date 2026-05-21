"""Backup / restore de la base Postgres via aiodocker exec.

Le backend a déjà accès au socket Docker (mount `/var/run/docker.sock`),
on lance donc `pg_dump` / `psql` à l'intérieur du container postgres
sans dépendre de pg_dump dans l'image backend.

Le format est `.sql.gz` : SQL plein-texte gzippé. Le dump utilise
`--clean --if-exists --no-owner --no-privileges` pour rester rejouable
sur n'importe quelle base sans dépendance sur les ownerships.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiodocker
import structlog

_log = structlog.get_logger(__name__)

POSTGRES_CONTAINER = os.environ.get(
    "AGFLOW_POSTGRES_CONTAINER", "agflow-postgres"
)


def _slugify(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def export_filename(schedule_name: str | None = None) -> str:
    """Nom de fichier d'export horodaté UTC, préfixé du nom de planification si fourni."""
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    base = f"agflow-db-{ts}.sql.gz"
    if schedule_name:
        slug = _slugify(schedule_name)
        return f"{slug}-{base}" if slug else base
    return base


_DUMP_CMD = (
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
    "--clean --if-exists --no-owner --no-privileges | gzip"
)
_RESTORE_CMD = (
    'gunzip -c | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
)


async def stream_dump() -> AsyncIterator[bytes]:
    """Stream le pg_dump gzippé du container postgres.

    Yields des chunks bytes pipés directement dans une StreamingResponse
    FastAPI. aiodocker.exec.start(detach=False) retourne un Stream
    asynchrone dont read_out() rend des Message {data, stream}, déjà
    démultiplexées par stream_id (1=stdout, 2=stderr) — on ne keep que
    stdout, le pg_dump | gzip envoie ses bytes binaires sur stdout pur.
    """
    docker = aiodocker.Docker()
    try:
        container = await docker.containers.get(POSTGRES_CONTAINER)
        exec_obj = await container.exec(
            cmd=["sh", "-c", _DUMP_CMD],
            stdout=True,
            stderr=False,
        )
        async with exec_obj.start(detach=False) as stream:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                # msg.stream : 1 = stdout, 2 = stderr
                if msg.stream == 1 and msg.data:
                    yield msg.data
        info = await exec_obj.inspect()
        exit_code = info.get("ExitCode", 0)
        if exit_code != 0:
            raise RuntimeError(f"pg_dump exited with code {exit_code}")
    finally:
        await docker.close()


async def restore_dump(stream_in: AsyncIterator[bytes]) -> dict:
    """Restore depuis un stream gzippé.

    Pipe le contenu dans `gunzip -c | psql` via docker exec stdin.
    Retourne un dict avec exit_code + tail des logs (utile pour l'UI).

    DESTRUCTIF : le dump contient `--clean --if-exists`, donc les tables
    existantes sont DROP avant recréation.
    """
    docker = aiodocker.Docker()
    try:
        container = await docker.containers.get(POSTGRES_CONTAINER)
        exec_obj = await container.exec(
            cmd=["sh", "-c", _RESTORE_CMD],
            stdin=True,
            stdout=True,
            stderr=True,
        )
        output_chunks: list[bytes] = []
        async with exec_obj.start(detach=False) as stream:
            # Push le contenu gzippé en stdin
            async for chunk in stream_in:
                if chunk:
                    await stream.write_in(chunk)
            # Signaler EOF côté stdin
            await stream.close()
            # Lire le tail du output (stdout/stderr de psql)
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                if msg.data:
                    output_chunks.append(msg.data)
                    if sum(len(c) for c in output_chunks) > 64 * 1024:
                        output_chunks = output_chunks[-50:]
        info = await exec_obj.inspect()
        exit_code = info.get("ExitCode") or 0
        tail = b"".join(output_chunks).decode("utf-8", errors="replace")[-2000:]
        _log.info("db_backup.restore_done", exit_code=exit_code)
        return {"exit_code": exit_code, "tail": tail}
    finally:
        await docker.close()
