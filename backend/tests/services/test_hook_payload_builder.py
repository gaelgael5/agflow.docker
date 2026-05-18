"""Tests du builder de payload hook v5 conforme §4."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agflow.services.hook_payload_builder import build_task_completed_payload


def test_build_completed_payload():
    hook_id = uuid4()
    payload = build_task_completed_payload(
        hook_id=hook_id,
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="architect-v1",
        container_id="ctr_xyz",
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result={"summary": "done", "artifacts": []},
        error=None,
        metadata={"duration_ms": 1234},
    )
    assert payload["hook_id"] == str(hook_id)
    assert payload["status"] == "completed"
    assert payload["result"] == {"summary": "done", "artifacts": []}
    assert payload["error"] is None


def test_build_failed_payload():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=None,
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result=None,
        error={"code": "AGENT_OOM", "message": "out of memory"},
        metadata={},
    )
    assert payload["status"] == "failed"
    assert payload["error"] == {"code": "AGENT_OOM", "message": "out of memory"}
    assert payload["result"] is None
    assert payload["project_runtime_id"] is None


def test_build_cancelled_payload_result_can_be_null():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="cancelled",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result=None,
        error={"code": "USER_CANCELLED", "message": "kill"},
        metadata={},
    )
    assert payload["status"] == "cancelled"
    assert payload["result"] is None
    assert payload["error"]["code"] == "USER_CANCELLED"


def test_iso_dates_are_strings():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result={"summary": "x"},
        error=None,
        metadata={},
    )
    assert isinstance(payload["started_at"], str)
    assert isinstance(payload["completed_at"], str)
    assert payload["started_at"].endswith("Z") or "+" in payload["started_at"]
