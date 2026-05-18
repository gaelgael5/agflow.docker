"""Tests du provisioning_worker workflow."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_process_pending_renders_jinja_marks_ready(
    fresh_db, mock_pending_workflow_runtime
):
    """Le worker rend les connection_params Jinja et marque status='ready'."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Runtime passé à deployed
    runtime_row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert runtime_row["status"] == "deployed"

    # Instances passées à ready avec connection_params rendus
    pri_rows = await fresh_db.fetch(
        """
        SELECT provisioning_status, connection_params
        FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    for r in pri_rows:
        assert r["provisioning_status"] == "ready"
        # vars Jinja remplacées (pas de '{{' dans le JSON rendu)
        assert "{{" not in str(r["connection_params"])


async def test_process_pending_marks_failed_on_jinja_error(
    fresh_db, mock_pending_workflow_runtime_with_bad_jinja
):
    """Une var Jinja manquante → instance.status='failed' + error_message."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime_with_bad_jinja["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Runtime marqué failed car au moins 1 instance failed
    runtime_row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert runtime_row["status"] == "failed"

    pri_rows = await fresh_db.fetch(
        """
        SELECT provisioning_status, error_message
        FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    failed = [r for r in pri_rows if r["provisioning_status"] == "failed"]
    assert len(failed) >= 1
    assert "undefined var" in failed[0]["error_message"].lower()


async def test_process_pending_ignores_saas_runtimes(
    fresh_db, mock_pending_saas_runtime
):
    """Les runtimes SaaS (user_id NOT NULL) ne sont PAS traités par ce worker."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_saas_runtime["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Status inchangé (toujours pending)
    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert row["status"] == "pending"


async def test_process_pending_skips_deleted_runtimes(
    fresh_db, mock_pending_workflow_runtime
):
    """Un runtime avec deleted_at NOT NULL est ignoré."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime["runtime_id"]
    await fresh_db.execute(
        "UPDATE project_runtimes SET deleted_at = now() WHERE id = $1",
        runtime_id,
    )
    await provisioning_worker.process_pending_runtimes()

    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert row["status"] == "pending"  # inchangé
