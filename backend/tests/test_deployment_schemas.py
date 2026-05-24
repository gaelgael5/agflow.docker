from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from agflow.schemas.products import (
    DeploymentSummary,
    ExecuteStepRequest,
    GenerateRequest,
    StepLog,
)


def test_deployment_summary_has_wizard_fields():
    d = DeploymentSummary(
        id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        status="step_complete",
        current_step_index=1,
        accumulated_env={"KC_CLIENT_ID": "abc"},
        step_logs=[{"step_index": 0, "lines": ["ok"], "exit_code": 0}],
        generated_secrets={},
        nullable_secrets=[],
        generated_data={},
        group_servers={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert d.current_step_index == 1
    assert d.accumulated_env["KC_CLIENT_ID"] == "abc"
    assert isinstance(d.step_logs[0], StepLog)


def test_generate_request_defaults():
    r = GenerateRequest()
    assert r.group_vars == {}
    assert r.user_secrets == {}


def test_execute_step_request_instantiable():
    r = ExecuteStepRequest()
    assert r is not None


def test_step_log_model():
    s = StepLog(step_index=0, lines=["line1"], exit_code=0)
    assert s.exit_code == 0
    assert s.lines == ["line1"]
    assert s.started_at is None
    assert s.ended_at is None


def test_deployment_status_extended_values():
    """Vérifie que les nouveaux statuts wizard sont acceptés."""
    for status in (
        "draft",
        "generated",
        "executing_step",
        "step_complete",
        "step_failed",
        "before_complete",
        "deploying",
        "deployed",
        "failed",
    ):
        d = DeploymentSummary(
            id=uuid4(),
            project_id=uuid4(),
            user_id=uuid4(),
            status=status,  # type: ignore[arg-type]
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert d.status == status
