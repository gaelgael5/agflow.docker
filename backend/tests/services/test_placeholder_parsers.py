# backend/tests/services/test_placeholder_parsers.py
"""Tests unitaires purs des parsers de placeholders. Aucun I/O."""

from __future__ import annotations

from agflow.services.placeholder_parsers import (
    ENV_MACHINE_RE,
    ENV_REF_RE,
    SIMPLE_VAR_RE,
    UNKNOWN_BRACE_RE,
    VAULT_REF_RE,
    parse_env_machine_ref,
    parse_env_text,
)


class TestEnvMachineRef:
    def test_parses_machine_and_var(self) -> None:
        result = parse_env_machine_ref("${env-machine://keycloak1:KC_ADMIN_PASSWORD}")
        assert result == ("keycloak1", "KC_ADMIN_PASSWORD")

    def test_returns_none_for_non_machine_ref(self) -> None:
        assert parse_env_machine_ref("${env://NAME}") is None
        assert parse_env_machine_ref("plain value") is None
        assert parse_env_machine_ref("") is None

    def test_strips_surrounding_whitespace(self) -> None:
        result = parse_env_machine_ref("  ${env-machine://m1:VAR}  ")
        assert result == ("m1", "VAR")


class TestEnvText:
    def test_parses_key_value_lines(self) -> None:
        text = "FOO=bar\nBAZ=qux\n"
        assert parse_env_text(text) == {"FOO": "bar", "BAZ": "qux"}

    def test_ignores_comments_and_blank_lines(self) -> None:
        text = "# comment\n\nFOO=bar\n"
        assert parse_env_text(text) == {"FOO": "bar"}

    def test_ignores_lines_without_equals(self) -> None:
        text = "FOO=bar\nnokey\nBAZ=qux\n"
        assert parse_env_text(text) == {"FOO": "bar", "BAZ": "qux"}

    def test_returns_empty_dict_for_empty_input(self) -> None:
        assert parse_env_text("") == {}
        assert parse_env_text(None) == {}  # type: ignore[arg-type]


class TestRegexPatterns:
    def test_env_machine_re_matches_only_well_formed_refs(self) -> None:
        assert ENV_MACHINE_RE.findall("${env-machine://m1:VAR}") == [("m1", "VAR")]
        assert ENV_MACHINE_RE.findall("${env://NAME}") == []

    def test_vault_re_matches(self) -> None:
        assert VAULT_REF_RE.findall("${vault://api:SECRET_NAME}") == ["SECRET_NAME"]

    def test_env_ref_re_matches(self) -> None:
        assert ENV_REF_RE.findall("${env://CONFIG}") == ["CONFIG"]

    def test_simple_var_re_matches_uppercase_only(self) -> None:
        # SIMPLE_VAR_RE matches ${VAR} or $VAR with [A-Z_][A-Z0-9_]*
        text = "${FOO} $BAR ${lower} ${MIX_3}"
        matches = [m.group(1) or m.group(2) for m in SIMPLE_VAR_RE.finditer(text)]
        assert matches == ["FOO", "BAR", "MIX_3"]

    def test_unknown_brace_re_catches_residual_braces(self) -> None:
        # Used to detect ${...} that didn't match any of the 4 patterns
        assert UNKNOWN_BRACE_RE.findall("${foo-bar}") == ["foo-bar"]
        assert UNKNOWN_BRACE_RE.findall("${non.standard}") == ["non.standard"]

    def test_unknown_brace_re_also_matches_recognized_patterns(self) -> None:
        # UNKNOWN_BRACE_RE est un détecteur RÉSIDUEL : il match TOUT ${...}.
        # Ne l'utiliser qu'APRÈS avoir substitué les 4 patterns reconnus,
        # sinon il considérera ${vault://…} et autres comme "non reconnus".
        assert UNKNOWN_BRACE_RE.findall("${env://FOO}") == ["env://FOO"]
        assert UNKNOWN_BRACE_RE.findall("${vault://api:X}") == ["vault://api:X"]
        assert UNKNOWN_BRACE_RE.findall("${env-machine://m:V}") == ["env-machine://m:V"]
        assert UNKNOWN_BRACE_RE.findall("${FOO}") == ["FOO"]
