from __future__ import annotations

from agflow.services.container_runner import expand_shell_vars


def test_self_reference_falls_back_to_default():
    # Param value that references itself — common pattern from the default
    # Dockerfile.json template.
    extra = {"WORKSPACE_PATH": "${WORKSPACE_PATH:-./workspace}"}
    out = expand_shell_vars("${WORKSPACE_PATH:-./workspace}", extra)
    assert out == "./workspace"


def test_self_reference_no_default_returns_empty():
    extra = {"FOO": "${FOO}"}
    out = expand_shell_vars("${FOO}", extra)
    assert out == ""


def test_normal_lookup_still_works():
    extra = {"BAR": "concrete-value"}
    out = expand_shell_vars("prefix-${BAR}-suffix", extra)
    assert out == "prefix-concrete-value-suffix"


def test_default_used_when_var_missing():
    out = expand_shell_vars("${MISSING:-fallback}", {})
    assert out == "fallback"


def test_self_reference_in_brace_only_form_caught():
    # Even without a default in the value, ${VAR} inside the value is detected.
    extra = {"X": "prefix-${X}-suffix"}
    out = expand_shell_vars("${X:-DEFAULT}", extra)
    assert out == "DEFAULT"
