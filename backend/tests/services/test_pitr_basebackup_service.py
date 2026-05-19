"""Tests pour pitr_basebackup_service — ensure_stanza + list/get/trigger."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from agflow.services import pitr_basebackup_service
from agflow.services.pitr_basebackup_service import (
    BasebackupNotFoundError,
    BasebackupRunningError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# ensure_stanza
# ---------------------------------------------------------------------------


async def test_ensure_stanza_creates_if_missing():
    """Si `pgbackrest info` retourne vide (ou status != 0), stanza-create est appelé."""
    # 1er appel (info) renvoie vide ; 2e appel (stanza-create) succès
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        (0, "", ""),                # info → vide (aucune stanza)
        (0, "stanza created", ""),  # stanza-create succès
    ]
    with patch("agflow.services.pitr_basebackup_service._pg_exec", mock_exec):
        await pitr_basebackup_service.ensure_stanza()
    assert mock_exec.call_count == 2
    # Le 2e appel doit être stanza-create
    args_call_2 = mock_exec.call_args_list[1].args[0]
    assert "stanza-create" in args_call_2


async def test_ensure_stanza_idempotent_if_already_exists():
    """Si `pgbackrest info` retourne déjà la stanza agflow, stanza-create n'est PAS appelé."""
    info_existing = '[{"name":"agflow","status":{"code":0}}]'
    mock_exec = AsyncMock()
    mock_exec.side_effect = [(0, info_existing, "")]
    with patch("agflow.services.pitr_basebackup_service._pg_exec", mock_exec):
        await pitr_basebackup_service.ensure_stanza()
    assert mock_exec.call_count == 1  # uniquement info, pas de stanza-create


# ---------------------------------------------------------------------------
# list / get  (DB-dependent → DONE_WITH_CONCERNS si LXC 201 injoignable)
# ---------------------------------------------------------------------------


async def test_list_basebackups_returns_empty_when_none():
    await reset_schema_and_migrate()
    items = await pitr_basebackup_service.list_basebackups()
    assert items == []


async def test_get_basebackup_raises_when_missing():
    await reset_schema_and_migrate()
    with pytest.raises(BasebackupNotFoundError):
        await pitr_basebackup_service.get_basebackup(uuid4())


# ---------------------------------------------------------------------------
# trigger_basebackup_now  (DB + _pg_exec mocké)
# ---------------------------------------------------------------------------


async def test_trigger_basebackup_now_inserts_and_marks_ok():
    """Happy path: INSERT 'running' → pgbackrest backup mocké OK → UPDATE 'ok' avec label parsé."""
    await reset_schema_and_migrate()

    backup_stdout = "P00   INFO: backup label = 20260520-030000F\n"
    info_json = json.dumps([{
        "name": "agflow",
        "status": {"code": 0},
        "backup": [{"label": "20260520-030000F", "info": {"size": 1234567}}],
    }])

    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        (0, info_json, ""),       # ensure_stanza → info (stanza existe)
        (0, backup_stdout, ""),   # pgbackrest backup
        (0, info_json, ""),       # _label_size_from_info
    ]

    with patch("agflow.services.pitr_basebackup_service._pg_exec", mock_exec):
        bid = await pitr_basebackup_service.trigger_basebackup_now(actor_user_id=None)

    assert isinstance(bid, UUID)
    items = await pitr_basebackup_service.list_basebackups()
    assert len(items) == 1
    assert items[0].pgbackrest_label == "20260520-030000F"
    assert items[0].status == "ok"
    assert items[0].size_bytes == 1234567


async def test_trigger_basebackup_now_raises_if_already_running():
    """Si un basebackup est déjà en status='running', lever BasebackupRunningError."""
    await reset_schema_and_migrate()

    from agflow.db.pool import execute as _execute

    await _execute(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, status) "
        "VALUES ('running-x', now(), 'running')"
    )

    with pytest.raises(BasebackupRunningError):
        await pitr_basebackup_service.trigger_basebackup_now(actor_user_id=None)
