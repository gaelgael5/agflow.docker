# backend/tests/services/test_input_resolver.py
"""Tests unitaires d'input_resolver. Mocks pour les dépendances DB."""

from __future__ import annotations

from agflow.services.input_resolver import UnresolvedPlaceholderError


class TestUnresolvedPlaceholderError:
    def test_carries_kind_ref_detail_varname(self) -> None:
        err = UnresolvedPlaceholderError(
            kind="machine_not_found",
            ref="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
            detail="machine 'keycloak1' inconnue",
            var_name="KC_ADMIN_PASSWORD",
        )
        assert err.kind == "machine_not_found"
        assert err.ref == "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"
        assert err.detail == "machine 'keycloak1' inconnue"
        assert err.var_name == "KC_ADMIN_PASSWORD"

    def test_str_contains_useful_info(self) -> None:
        err = UnresolvedPlaceholderError(
            kind="env_machine_var_empty",
            ref="${env-machine://m1:VAR}",
            detail="variable 'VAR' vide sur 'm1'",
            var_name="VAR",
        )
        msg = str(err)
        assert "env_machine_var_empty" in msg
        assert "VAR" in msg
