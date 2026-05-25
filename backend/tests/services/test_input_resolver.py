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
)

pytestmark = pytest.mark.asyncio

MACHINE_ID = uuid4()


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
    """Mock machines_service.get_by_name — lookup machine par nom (cas env-machine://)."""
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
    async def test_literal_value_preserved(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"PORT": "8080"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"PORT": "8080"}

    async def test_simple_var_resolved_from_env_text(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"HOST": "${MY_HOST}"},
            target_machine_id=MACHINE_ID,
            env_text="MY_HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"HOST": "example.com"}

    async def test_env_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"API_URL": "${env://API_URL}"},
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={"API_URL": "https://api.example.com"},
        )
        assert result == {"API_URL": "https://api.example.com"}

    async def test_vault_ref_resolved_from_platform_secrets(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"TOKEN": "${vault://api:GITHUB_TOKEN}"},
            target_machine_id=MACHINE_ID,
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
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"KC_ADMIN_PASSWORD": "s3cret"}
        mock_get_machine_by_name.assert_awaited_with("keycloak1")
        mock_resolve_for_named_machine.assert_awaited_with(kc_id)

    async def test_mixed_value_prefix_ref_suffix(self, mock_resolve_for_machine) -> None:
        result = await resolve_input_values(
            input_values={"URL": "https://${HOST}:8080/api"},
            target_machine_id=MACHINE_ID,
            env_text="HOST=example.com",
            platform_secrets_map={},
        )
        assert result == {"URL": "https://example.com:8080/api"}


class TestResolveInputValuesErrors:
    async def test_empty_value_raises_value_empty(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"PASSWORD": ""},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "value_empty"
        assert exc_info.value.var_name == "PASSWORD"

    async def test_simple_var_not_in_env_raises(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"HOST": "${MY_HOST}"},
                target_machine_id=MACHINE_ID,
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
                target_machine_id=MACHINE_ID,
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
                target_machine_id=MACHINE_ID,
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
                target_machine_id=MACHINE_ID,
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
                target_machine_id=MACHINE_ID,
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
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "env_machine_var_not_found"
        assert "MISSING" in exc_info.value.detail

    async def test_env_machine_var_empty_raises(
        self,
        mock_get_machine_by_name,
        mock_resolve_for_named_machine,
    ) -> None:
        mock_get_machine_by_name.return_value = SimpleNamespace(id=uuid4(), name="m1")
        mock_resolve_for_named_machine.return_value = {"VAR": ""}
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${env-machine://m1:VAR}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind in ("env_machine_var_empty", "env_machine_var_not_found")

    async def test_unknown_brace_raises_unknown_ref(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"X": "${foo-bar}"},
                target_machine_id=MACHINE_ID,
                env_text="",
                platform_secrets_map={},
            )
        assert exc_info.value.kind == "unknown_ref"
        assert "foo-bar" in exc_info.value.detail

    async def test_fail_fast_stops_at_first_error(self, mock_resolve_for_machine) -> None:
        with pytest.raises(UnresolvedPlaceholderError) as exc_info:
            await resolve_input_values(
                input_values={"FIRST": "${MISSING_A}", "SECOND": "${MISSING_B}"},
                target_machine_id=MACHINE_ID,
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
            target_machine_id=MACHINE_ID,
            env_text="",
            platform_secrets_map={},
        )
        assert result == {"X": "literal-${OTHER}-value"}
