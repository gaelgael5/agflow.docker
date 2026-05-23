from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_one
from agflow.schemas.restore_wizard import RestoreExecuteRequest, RestoreJobStatus
from agflow.services import db_backup
from agflow.services.remote_backup_providers.factory import get_provider
from agflow.services.restore_wizard_vault_service import get_vault_secret_value

_log = structlog.get_logger(__name__)

_CHUNK = 65536


async def create_job() -> UUID:
    row = await fetch_one(
        "INSERT INTO restore_jobs (status) VALUES ('running') RETURNING id, status, log, created_at, completed_at",
    )
    return row["id"]


async def get_job(job_id: UUID) -> RestoreJobStatus | None:
    row = await fetch_one(
        "SELECT id, status, log, created_at, completed_at FROM restore_jobs WHERE id = $1",
        job_id,
    )
    if row is None:
        return None
    return RestoreJobStatus(
        job_id=row["id"],
        status=row["status"],
        log=row["log"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


async def _append_log(job_id: UUID, msg: str) -> None:
    await execute(
        "UPDATE restore_jobs SET log = log || $1 WHERE id = $2",
        msg + "\n",
        job_id,
    )


async def _set_done(job_id: UUID, tail: str) -> None:
    await execute(
        "UPDATE restore_jobs SET status = 'done', log = log || $1, completed_at = now() WHERE id = $2",
        tail + "\n",
        job_id,
    )


async def _set_failed(job_id: UUID, error: str) -> None:
    await execute(
        "UPDATE restore_jobs SET status = 'failed', log = log || $1, completed_at = now() WHERE id = $2",
        "ERREUR : " + error + "\n",
        job_id,
    )


async def _resolve_credentials(req: RestoreExecuteRequest) -> dict[str, str | None]:
    credentials: dict[str, str | None] = {}
    for field, secret_name in req.vault_mappings.items():
        if secret_name:
            credentials[field] = await get_vault_secret_value(
                req.vault.url, req.vault.api_key, secret_name
            )
    return credentials


async def _stream_file(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            yield chunk


async def run_job(job_id: UUID, req: RestoreExecuteRequest) -> None:
    tmp_path: Path | None = None
    try:
        await _append_log(job_id, "Résolution des credentials vault...")
        credentials = await _resolve_credentials(req)

        filename = req.file_path.split("/")[-1]
        dir_path = "/".join(req.file_path.split("/")[:-1]) or "/"

        await _append_log(job_id, f"Téléchargement de {filename}...")
        provider = get_provider(req.connection_type, req.manual_fields, credentials)

        fd, tmp_str = tempfile.mkstemp(suffix=f"-{filename}")
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "wb") as fh:
                async for chunk in await provider.download_stream(dir_path, filename):
                    fh.write(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            tmp_path = None
            raise

        await _append_log(job_id, "Restauration de la base en cours...")
        result = await db_backup.restore_dump(_stream_file(tmp_path))

        if result["exit_code"] != 0:
            raise RuntimeError(
                f"pg_restore a échoué (code {result['exit_code']}) :\n{result['tail']}"
            )

        await _set_done(job_id, f"Restauration terminée.\n{result['tail']}")

    except Exception as exc:
        _log.error("restore_wizard.job_failed", job_id=str(job_id), error=str(exc))
        await _set_failed(job_id, str(exc))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
