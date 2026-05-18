"""Tests du helper Jinja récursif pour rendre les jsonb du workflow."""
from __future__ import annotations

import pytest

from agflow.services.jinja_render import (
    JinjaRenderError,
    render_jsonb_jinja,
)


def test_render_simple_string():
    out = render_jsonb_jinja("https://{{ runtime.host }}", {"runtime": {"host": "x.com"}})
    assert out == "https://x.com"


def test_render_dict_nested():
    src = {
        "url": "https://{{ runtime.host }}",
        "auth": {"token": "{{ runtime.token }}"},
    }
    ctx = {"runtime": {"host": "x.com", "token": "abc"}}
    out = render_jsonb_jinja(src, ctx)
    assert out == {"url": "https://x.com", "auth": {"token": "abc"}}


def test_render_list_of_strings():
    src = ["{{ runtime.host }}", "static", "{{ runtime.token }}"]
    out = render_jsonb_jinja(src, {"runtime": {"host": "x", "token": "y"}})
    assert out == ["x", "static", "y"]


def test_non_string_values_passthrough():
    src = {"port": 5432, "ssl": True, "name": "{{ runtime.host }}"}
    out = render_jsonb_jinja(src, {"runtime": {"host": "x"}})
    assert out == {"port": 5432, "ssl": True, "name": "x"}


def test_missing_var_raises():
    with pytest.raises(JinjaRenderError) as exc:
        render_jsonb_jinja("{{ runtime.missing }}", {"runtime": {}})
    assert "missing" in str(exc.value)


def test_sandbox_blocks_dunder_access():
    """SandboxedEnvironment doit refuser l'accès aux attributs __class__."""
    with pytest.raises(JinjaRenderError):
        render_jsonb_jinja(
            "{{ runtime.__class__.__name__ }}",
            {"runtime": {"x": 1}},
        )


def test_malformed_template_raises_jinja_render_error():
    """Une syntaxe Jinja invalide doit être convertie en JinjaRenderError."""
    with pytest.raises(JinjaRenderError):
        render_jsonb_jinja("{{ unclosed", {"runtime": {"x": 1}})
