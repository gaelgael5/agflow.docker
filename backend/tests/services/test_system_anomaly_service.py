from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_create_anomaly_deduplicates_open_anomalies():
    """Ne crée pas une nouvelle anomalie si une non-ack existe déjà pour (source, source_ref_id, severity)."""
    from agflow.services import system_anomaly_service as svc

    ref_id = uuid4()

    with patch("agflow.services.system_anomaly_service.fetch_one", AsyncMock(
        return_value={"id": 1}  # anomalie déjà ouverte
    )) as mock_fetch, \
    patch("agflow.services.system_anomaly_service.execute", AsyncMock()) as mock_exec:

        await svc.create_anomaly(
            severity="critical",
            anomaly_type="remote_push_failed",
            source="snapshot_remote_push",
            source_ref_id=ref_id,
            message="Connection refused",
            metadata={"remote_id": str(ref_id)},
        )

        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_create_anomaly_inserts_if_no_open():
    """Crée l'anomalie si aucune n'est ouverte pour ce (source, source_ref_id, severity)."""
    from agflow.services import system_anomaly_service as svc

    ref_id = uuid4()

    with patch("agflow.services.system_anomaly_service.fetch_one", AsyncMock(return_value=None)) as mock_fetch, \
    patch("agflow.services.system_anomaly_service.execute", AsyncMock()) as mock_exec:

        await svc.create_anomaly(
            severity="critical",
            anomaly_type="remote_push_failed",
            source="snapshot_remote_push",
            source_ref_id=ref_id,
            message="Connection refused",
        )

        mock_exec.assert_called_once()
