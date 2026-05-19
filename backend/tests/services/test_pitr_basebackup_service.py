"""Tests pour pitr_basebackup_service.ensure_stanza()."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agflow.services import pitr_basebackup_service

pytestmark = pytest.mark.asyncio


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
