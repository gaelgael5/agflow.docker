"""Tests pour les helpers Swarm du compose renderer (path A1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from agflow.services.compose_renderer_service import (
    _build_group_context,
    _to_yaml_filter,
)

# Les deux tests `test_seed_default_compose_template_*` ci-dessous lisent un
# template à `scripts/_prompts/seed-default-compose.sh.j2`, qui vit hors du
# build context backend/ — donc absent du container test. Le marker s'active
# seulement quand le template est trouvable (= en checkout repo local), pas
# quand on tourne pytest depuis l'image agflow-backend dans le LXC.
_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent
    / "scripts" / "_prompts" / "seed-default-compose.sh.j2"
)
_skip_if_template_missing = pytest.mark.skipif(
    not _TEMPLATE_PATH.exists(),
    reason=(
        "scripts/_prompts/seed-default-compose.sh.j2 hors build context "
        "backend/ — test pertinent uniquement en checkout repo local."
    ),
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


def _render_template(template_path: Path, context: dict) -> str:
    env = SandboxedEnvironment(
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    env.filters["to_yaml"] = _to_yaml_filter
    template = env.from_string(template_path.read_text(encoding="utf-8"))
    return template.render(**context)


@_skip_if_template_missing
def test_seed_default_compose_template_produces_valid_swarm_stack() -> None:
    """Le template seed-default-compose doit produire un YAML Swarm-stack valide."""
    template_path = (
        Path(__file__).parent.parent.parent / "scripts" / "_prompts" / "seed-default-compose.sh.j2"
    )
    assert template_path.exists(), f"Template introuvable : {template_path}"

    context = {
        "group": {"id": "g-1", "name": "g", "slug": "G"},
        "group_slug": "G",
        "network": "agflow_proj",
        "volumes": ["api-data"],
        "instances": [
            {
                "id": "inst-1",
                "group_id": "g-1",
                "instance_name": "inst",
                "catalog_id": "cat-1",
                "services": [
                    {
                        "id": "api",
                        "container_name": "inst-api",
                        "image": "nginx:1.27",
                        "ports": [80],
                        "environment": {"FOO": "bar"},
                        "volumes": [
                            {"name": "data", "mount": "/data", "docker_volume": "api-data"},
                        ],
                        "depends_on": [],
                        "labels": ["agflow.group_id=g-1"],
                        "networks": ["agflow_proj"],
                        "deploy": {
                            "replicas": 2,
                            "endpoint_mode": "dnsrr",
                            "placement": {"constraints": ["node.role == manager"]},
                            "restart_policy": {
                                "condition": "on-failure",
                                "delay": "10s",
                                "max_attempts": 5,
                            },
                        },
                    },
                ],
            },
        ],
    }

    rendered = _render_template(template_path, context)

    # Parsing YAML : doit etre valide
    parsed = yaml.safe_load(rendered)

    # Structure attendue
    assert "services" in parsed
    assert "inst-api" in parsed["services"]
    svc = parsed["services"]["inst-api"]

    assert svc["image"] == "nginx:1.27"
    assert svc["hostname"] == "inst-api"

    # Bloc deploy complet
    assert svc["deploy"]["replicas"] == 2
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"

    # Ports en long-form mode: host
    assert svc["ports"] == [{"target": 80, "published": 80, "mode": "host"}]

    # Network en overlay
    assert parsed["networks"]["agflow_proj"]["driver"] == "overlay"

    # Volumes declares
    assert "api-data" in parsed["volumes"]


@_skip_if_template_missing
def test_seed_default_compose_template_excludes_legacy_fields() -> None:
    """Le template ne doit PLUS contenir les directives compose-v1 obsoletes."""
    template_path = (
        Path(__file__).parent.parent.parent / "scripts" / "_prompts" / "seed-default-compose.sh.j2"
    )
    content = template_path.read_text(encoding="utf-8")

    assert "container_name:" not in content, (
        "container_name doit etre supprime (Swarm gere les noms)"
    )
    assert "restart:" not in content, (
        "restart top-level doit etre supprime (Swarm utilise deploy.restart_policy)"
    )
    assert "driver: bridge" not in content, "driver: bridge doit etre remplace par driver: overlay"
