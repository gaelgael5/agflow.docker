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


def export_filename() -> str:
    """Nom de fichier d'export horodaté UTC."""
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"agflow-db-{ts}.sql.gz"


_DUMP_CMD = (
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
    "--clean --if-exists --no-owner --no-privileges | gzip"
)
_RESTORE_CMD = (
    'gunzip -c | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
)


def _demux_docker_frames(buf: bytes) -> tuple[bytes, bytes]:
    """Split le buffer multiplexed Docker en (stdout, leftover).

    Format de chaque frame : 1 byte stream_id (1=stdout, 2=stderr) + 3 bytes
    padding + 4 bytes big-endian length + payload. On accumule un buffer
    car un message WS peut contenir plusieurs frames OU une frame partielle.
    Retourne le payload stdout extrait et le reliquat à reprocesser au tour
    suivant.
    """
    out = bytearray()
    pos = 0
    while pos + 8 <= len(buf):
        stream_id = buf[pos]
        size = int.from_bytes(buf[pos + 4 : pos + 8], "big")
        if pos + 8 + size > len(buf):
            break  # frame incomplete — wait for more bytes
        payload = buf[pos + 8 : pos + 8 + size]
        if stream_id == 1:  # stdout uniquement
            out.extend(payload)
        pos += 8 + size
    return bytes(out), buf[pos:]


async def stream_dump() -> AsyncIterator[bytes]:
    """Stream le pg_dump gzippé du container postgres.

    Yields des chunks bytes qui peuvent être pipés directement dans
    une StreamingResponse FastAPI. Le protocole Docker exec sans TTY
    encapsule chaque chunk dans un header 8 bytes (stream_id + length),
    qu'on dépacke pour ne yielder que le stdout brut.
    """
    docker = aiodocker.Docker()
    try:
        container = await docker.containers.get(POSTGRES_CONTAINER)
        exec_obj = await container.exec(
            cmd=["sh", "-c", _DUMP_CMD],
            stdout=True,
            stderr=False,
        )
        ws = await exec_obj.start(detach=False)
        leftover = b""
        try:
            while True:
                msg = await ws.receive()
                if msg.type.name in ("CLOSED", "CLOSING", "ERROR"):
                    break
                if not msg.data:
                    continue
                buf = leftover + msg.data
                payload, leftover = _demux_docker_frames(buf)
                if payload:
                    yield payload
        finally:
            await ws.close()
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
        ws = await exec_obj.start(detach=False)
        output_chunks: list[bytes] = []
        try:
            # Push le contenu en stdin
            async for chunk in stream_in:
                if chunk:
                    await ws.send_bytes(chunk)
            # Signaler EOF
            await ws.close()
            # Lire ce que psql a écrit (juste pour le retour)
            while True:
                msg = await ws.receive()
                if msg.type.name in ("CLOSED", "CLOSING", "ERROR"):
                    break
                if msg.data:
                    output_chunks.append(msg.data)
                    if sum(len(c) for c in output_chunks) > 64 * 1024:
                        # Garde la fin uniquement
                        output_chunks = output_chunks[-50:]
        except Exception:
            # ws probablement déjà closed côté send_bytes EOF
            pass
        info = await exec_obj.inspect()
        exit_code = info.get("ExitCode") or 0
        tail = b"".join(output_chunks).decode("utf-8", errors="replace")[-2000:]
        _log.info("db_backup.restore_done", exit_code=exit_code)
        return {"exit_code": exit_code, "tail": tail}
    finally:
        await docker.close()
