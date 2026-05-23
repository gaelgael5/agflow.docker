from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agflow.schemas.restore_wizard import RestoreExecuteRequest, VaultRef
from agflow.services.restore_wizard_job_service import run_job


@pytest.mark.asyncio
async def test_run_job_success():
    job_id = uuid4()

    async def fake_get_secret(_url, _key, name):
        return f"value-of-{name}"

    async def fake_stream():
        yield b"fake-backup-content"

    fake_provider = MagicMock()
    fake_provider.download_stream = AsyncMock(return_value=fake_stream())

    async def fake_restore(_stream):
        return {"exit_code": 0, "tail": "Restore OK"}

    executed = []

    async def fake_execute(sql, *args):
        executed.append((sql, args))

    with (
        patch(
            "agflow.services.restore_wizard_job_service.get_vault_secret_value",
            side_effect=fake_get_secret,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.get_provider",
            return_value=fake_provider,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.db_backup.restore_dump",
            side_effect=fake_restore,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.execute",
            side_effect=fake_execute,
        ),
    ):
        req = RestoreExecuteRequest(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1", "port": "22"},
            vault_mappings={"username": "remote-backups/user", "private_key": "certificates/key"},
            vault=VaultRef(url="https://vault.test", api_key="k"),
            file_path="/backups/dump.sql.gz",
        )
        await run_job(job_id, req)

    done_calls = [c for c in executed if "done" in str(c)]
    assert done_calls, "Le job doit être marqué 'done'"


@pytest.mark.asyncio
async def test_run_job_restore_failure():
    job_id = uuid4()

    async def fake_get_secret(_url, _key, name):
        return f"v-{name}"

    async def fake_stream():
        yield b"data"

    fake_provider = MagicMock()
    fake_provider.download_stream = AsyncMock(return_value=fake_stream())

    async def fake_restore_fail(_stream):
        return {"exit_code": 1, "tail": "ERROR: relation already exists"}

    executed = []

    async def fake_execute(sql, *args):
        executed.append((sql, args))

    with (
        patch(
            "agflow.services.restore_wizard_job_service.get_vault_secret_value",
            side_effect=fake_get_secret,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.get_provider",
            return_value=fake_provider,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.db_backup.restore_dump",
            side_effect=fake_restore_fail,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.execute",
            side_effect=fake_execute,
        ),
    ):
        req = RestoreExecuteRequest(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1"},
            vault_mappings={"username": "remote-backups/u"},
            vault=VaultRef(url="https://v.test", api_key="k"),
            file_path="/b/dump.sql.gz",
        )
        await run_job(job_id, req)

    failed_calls = [c for c in executed if "failed" in str(c)]
    assert failed_calls, "Le job doit être marqué 'failed'"
