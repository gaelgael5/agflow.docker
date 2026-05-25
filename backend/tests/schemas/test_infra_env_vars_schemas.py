"""Tests round-trip Pydantic pour les schémas infra_env_vars."""

from __future__ import annotations

from uuid import uuid4


def test_project_env_vars_check_missing_reason_round_trip() -> None:
    from agflow.schemas.infra_env_vars import (
        ProjectEnvVarsCheckMissing,
        ProjectEnvVarsCheckMissingReason,
    )

    reason = ProjectEnvVarsCheckMissingReason(
        var_name="KC_ADMIN_PASSWORD",
        kind="machine_not_found",
        ref="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
        detail="machine 'keycloak1' inconnue",
    )
    item = ProjectEnvVarsCheckMissing(
        group_script_id=uuid4(),
        script_id=uuid4(),
        script_name="create-oidc-client",
        group_id=uuid4(),
        group_name="primary",
        machine_id=None,
        machine_name=None,
        target_kind="deployment_host",
        missing=[reason],
    )
    dumped = item.model_dump()
    assert dumped["missing"][0]["kind"] == "machine_not_found"
    assert dumped["missing"][0]["var_name"] == "KC_ADMIN_PASSWORD"
    assert dumped["missing"][0]["ref"] == "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"
    assert dumped["missing"][0]["detail"] == "machine 'keycloak1' inconnue"


def test_project_env_vars_check_missing_reason_validates_kind() -> None:
    """Un kind hors Literal doit être rejeté."""
    import pytest
    from pydantic import ValidationError

    from agflow.schemas.infra_env_vars import ProjectEnvVarsCheckMissingReason

    with pytest.raises(ValidationError):
        ProjectEnvVarsCheckMissingReason(
            var_name="X",
            kind="not_a_real_kind",
            ref="",
            detail="",  # type: ignore[arg-type]
        )


def test_project_env_vars_check_missing_no_legacy_field() -> None:
    """L'ancien champ `missing_env_vars` ne doit plus exister."""
    from agflow.schemas.infra_env_vars import ProjectEnvVarsCheckMissing

    schema = ProjectEnvVarsCheckMissing.model_json_schema()
    properties = schema.get("properties", {})
    assert "missing_env_vars" not in properties
    assert "missing" in properties
