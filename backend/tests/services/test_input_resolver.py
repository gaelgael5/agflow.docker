# backend/tests/services/test_input_resolver.py
"""Tests unitaires d'input_resolver. Mocks pour les dépendances DB."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.services.input_resolver import (
    UnresolvedPlaceholderError,
    resolve_input_values,
    resolve_input_values_collect,
)


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
            kind="env_machine_var_not_found",
            ref="${env-machine://m1:VAR}",
            detail="variable 'VAR' absente sur 'm1'",
            var_name="VAR",
        )
        msg = str(err)
        assert "env_machine_var_not_found" in msg
        assert "VAR" in msg
        assert "m1" in msg  # ref content should appear

    def test_str_without_var_name(self) -> None:
        err = UnresolvedPlaceholderError(
            kind="value_empty",
            ref="",
            detail="valeur vide",
        )
        msg = str(err)
        assert "value_empty" in msg
        assert "valeur vide" in msg
        assert "None" not in msg  # var_name=None must NOT leak as literal
        assert "var=" not in msg  # var_name was None so var= section omitted


@pytest.fixture
def mock_resolve_for_machine():
    """Mock infra_env_vars_service.resolve_for_machine — retourne env vars de la machine cible."""
    with patch(
        "agflow.services.input_resolver.infra_env_vars_service.resolve_for_machine",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = {}
        yield m


@pytest.fixture
def mock_get_machine_by_name():
    """Mock infra_machines_service.get_by_name. Utilise create=True car la
    fonction sera ajoutée en T5 — à retirer une fois T5 mergée."""
    with patch(
        "agflow.services.input_resolver.infra_machines_service.get_by_name",
        new_callable=AsyncMock,
        create=True,
    ) as m:
        m.return_value = None  # par défaut : machine inconnue
        yield m


@pytest.fixture
def mock_resolve_for_named_machine():
    """Mock infra_env_vars_service.resolve_for_machine pour une machine arbitraire."""
    with patch(
        "agflow.services.input_resolver.infra_env_vars_service.resolve_for_machine",
        new_callable=AsyncMock,
    ) as m:
        yield m


class TestResolveInputValuesFailFast:
    pytestmark = pytest.mark.asyncio

    async def test_literal_value_preserved(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"PORT": "8080"},
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"PORT": "8080"}

    async def test_simple_var_resolved_from_env_text(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"HOST": "${MY_HOST}"},
            env_text="MY_HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"HOST": "example.com"}

    async def test_env_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"API_URL": "${env://API_URL}"},
            env_text="",
            platform_secrets_map={"API_URL": "https://api.example.com"},
        )
        assert result == {"API_URL": "https://api.example.com"}

    async def test_vault_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"TOKEN": "${vault://api:GITHUB_TOKEN}"},
            env_text="",
            platform_secrets_map={"GITHUB_TOKEN": "ghp_xxx"},
        )
        assert result == {"TOKEN": "ghp_xxx"}

    async def test_env_machine_ref_resolved(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        kc_id = uuid4()
        mock_get_machine_by_name.return_value = SimpleNamespace(id=kc_id, name="keycloak1")
        mock_resolve_for_named_machine.return_value = {"KC_ADMIN_PASSWORD": "s3cret"}

        result = await resolve_input_values(
            input_values={"KC_ADMIN_PASSWORD": "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"},
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"KC_ADMIN_PASSWORD": "s3cret"}
        mock_get_machine_by_name.assert_awaited_with("keycloak1")
        mock_resolve_for_named_machine.assert_awaited_with(kc_id)

    async def test_mixed_value_prefix_ref_suffix(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"URL": "https://${HOST}:8080/api"},
            env_text="HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"URL": "https://example.com:8080/api"}


class TestResolveInputValuesErrors:
    pytestmark = pytest.mark.asyncio

    async def test_empty_value_raises_value_empty(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"PASSWORD": ""},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "value_empty"
        assert exc_info.value.var_name == "PASSWORD"

    async def test_simple_var_not_in_env_raises(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"HOST": "${MY_HOST}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "var_not_in_env"
        assert exc_info.value.var_name == "HOST"
        assert "MY_HOST" in exc_info.value.detail

    async def test_empty_var_in_env_raises(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"HOST": "${MY_HOST}"},
                env_text="MY_HOST=",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "var_not_in_env"

    async def test_env_ref_missing_raises_platform_secret_missing(
        self,
        mock_resolve_for_machine,
    ) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env://NO_SUCH}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "platform_secret_missing"

    async def test_vault_ref_missing_raises_platform_secret_missing(
        self,
        mock_resolve_for_machine,
    ) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${vault://api:NO_SUCH}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "platform_secret_missing"

    async def test_env_machine_unknown_machine_raises(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        mock_get_machine_by_name.return_value = None
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://ghost:VAR}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "machine_not_found"
        assert "ghost" in exc_info.value.detail

    async def test_env_machine_var_missing_raises(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"OTHER": "v"}
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://m1:MISSING}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "env_machine_var_not_found"
        assert "MISSING" in exc_info.value.detail

    async def test_env_machine_var_empty_returns_not_found(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        # resolve_for_machine filtre les empties — du point de vue d'input_resolver,
        # une variable vide en DB se présente comme absente. Un seul kind suffit.
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {}  # var "VAR" filtrée parce que vide
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://m1:VAR}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "env_machine_var_not_found"

    async def test_unknown_brace_raises_unknown_ref(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${foo-bar}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "unknown_ref"
        assert "foo-bar" in exc_info.value.detail

    async def test_fail_fast_stops_at_first_error(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"FIRST": "${MISSING_A}", "SECOND": "${MISSING_B}"},
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.var_name == "FIRST"

    async def test_no_recursion_in_env_machine_value(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"VAR": "literal-${OTHER}-value"}
        result = await resolve_input_values(
            input_values={"X": "${env-machine://m1:VAR}"},
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"X": "literal-${OTHER}-value"}


class TestResolveInputValuesCollect:
    pytestmark = pytest.mark.asyncio

    async def test_returns_resolved_and_errors(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={
                "OK": "${HOST}",
                "KO1": "${MISSING}",
                "KO2": "",
            },
            env_text="HOST=example.com",
            platform_secrets_map={},
        )
        assert resolved == {"OK": "example.com"}
        kinds = sorted([(e.var_name, e.kind) for e in errors])
        assert kinds == [("KO1", "var_not_in_env"), ("KO2", "value_empty")]

    async def test_empty_inputs(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={},
            env_text="",
            platform_secrets_map={},
        )
        assert resolved == {}
        assert errors == []

    async def test_all_errors_collected(self, mock_resolve_for_machine) -> None:
        resolved, errors = await resolve_input_values_collect(
            input_values={
                "A": "${env://NO_A}",
                "B": "${vault://api:NO_B}",
                "C": "${MISSING}",
            },
            env_text="",
            platform_secrets_map={},
        )
        assert resolved == {}
        assert len(errors) == 3
        kinds = {e.var_name: e.kind for e in errors}
        assert kinds == {
            "A": "platform_secret_missing",
            "B": "platform_secret_missing",
            "C": "var_not_in_env",
        }
