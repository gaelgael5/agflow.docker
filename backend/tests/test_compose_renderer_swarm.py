"""Tests pour les helpers Swarm du compose renderer (path A1)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from agflow.services.compose_renderer_service import (
    _build_group_context,
    _to_yaml_filter,
)


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


def _make_instance(name: str, group_id, catalog_id, variables: dict | None = None):
    return SimpleNamespace(
        id=uuid4(),
        instance_name=name,
        group_id=group_id,
        catalog_id=catalog_id,
        variables=variables or {},
        created_at="2026-04-30",
    )


def test_build_group_context_injects_default_deploy_when_recipe_has_none() -> None:
    group = SimpleNamespace(id=uuid4(), name="my-group")
    catalog_id = uuid4()
    instance = _make_instance("inst1", group.id, catalog_id)
    recipe = {
        "services": [
            {"id": "api", "image": "nginx:1.27", "ports": [80]},
        ],
    }
    block = _build_group_context(
        group=group,
        instances=[instance],
        all_instances=[instance],
        recipes_by_id={str(catalog_id): recipe},
        network="agflow",
    )

    svc = block["instances"][0]["services"][0]
    assert "deploy" in svc
    # Default deploy contient bien le bloc complet
    assert svc["deploy"]["replicas"] == 1
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert svc["deploy"]["placement"]["constraints"] == ["node.role == manager"]
    assert svc["deploy"]["restart_policy"]["condition"] == "on-failure"


def test_build_group_context_deep_merges_recipe_deploy_override() -> None:
    group = SimpleNamespace(id=uuid4(), name="my-group")
    catalog_id = uuid4()
    instance = _make_instance("inst1", group.id, catalog_id)
    recipe = {
        "services": [
            {
                "id": "api",
                "image": "nginx:1.27",
                "ports": [80],
                "deploy": {
                    "replicas": 3,
                    "resources": {"limits": {"memory": "512M"}},
                },
            },
        ],
    }
    block = _build_group_context(
        group=group,
        instances=[instance],
        all_instances=[instance],
        recipes_by_id={str(catalog_id): recipe},
        network="agflow",
    )

    svc = block["instances"][0]["services"][0]
    assert svc["deploy"]["replicas"] == 3
    assert svc["deploy"]["resources"]["limits"]["memory"] == "512M"
    # Defaults non-touches conserves
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert svc["deploy"]["restart_policy"]["max_attempts"] == 5
