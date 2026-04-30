"""Tests pour les helpers Swarm du compose renderer (path A1)."""

from __future__ import annotations

from agflow.services.compose_renderer_service import _to_yaml_filter


def test_to_yaml_filter_no_indent() -> None:
    out = _to_yaml_filter({"replicas": 1, "endpoint_mode": "dnsrr"}, indent=0)
    # Pas d'indentation, pas de newline final
    assert out == "replicas: 1\nendpoint_mode: dnsrr"


def test_to_yaml_filter_with_indent_pads_each_line() -> None:
    out = _to_yaml_filter(
        {"replicas": 2, "placement": {"constraints": ["node.role == manager"]}}, indent=6
    )
    expected = (
        "      replicas: 2\n      placement:\n        constraints:\n        - node.role == manager"
    )
    assert out == expected


def test_to_yaml_filter_handles_nested_dict() -> None:
    out = _to_yaml_filter({"a": {"b": {"c": 1}}}, indent=4)
    assert out == "    a:\n      b:\n        c: 1"


def test_to_yaml_filter_preserves_key_order() -> None:
    out = _to_yaml_filter({"z": 1, "a": 2}, indent=0)
    # sort_keys=False -> l'ordre d'insertion est preserve
    assert out == "z: 1\na: 2"
