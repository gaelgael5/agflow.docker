"""Tests purs (pas de DB, pas de Docker) pour build_service_spec().

Map un Dockerfile.json minimaliste vers un Swarm ServiceSpec valide.
"""
from __future__ import annotations

import os

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"

from agflow.services.container_runner import build_service_spec

_BASIC_PARAMS = """
{
  "docker": {
    "Container": {"Name": "agent-claude-{id}", "Image": "agflow-claude:{hash}"},
    "Network": {"Mode": "agflow-internal"},
    "Runtime": {"Init": true, "WorkingDir": "/app"},
    "Resources": {"Memory": "1g", "Cpus": "1.5"},
    "Environments": {"FOO": "bar"},
    "Mounts": []
  },
  "Params": {}
}
"""


def test_build_service_spec_returns_name_and_spec_dict() -> None:
    name, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    assert name == "agent-claude-xyz789"
    assert isinstance(spec, dict)
    assert "Name" in spec
    assert spec["Name"] == name


def test_build_service_spec_image_resolved_from_template() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    assert spec["TaskTemplate"]["ContainerSpec"]["Image"] == "agflow-claude:abc123"


def test_build_service_spec_env_list() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    env = spec["TaskTemplate"]["ContainerSpec"]["Env"]
    assert "FOO=bar" in env


def test_build_service_spec_resources_mapped() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    res = spec["TaskTemplate"]["Resources"]
    # 1g = 1 GiB = 1073741824 bytes
    assert res["Limits"]["MemoryBytes"] == 1073741824
    # 1.5 cpus = 1.5e9 nano-cpus
    assert res["Limits"]["NanoCPUs"] == 1500000000


def test_build_service_spec_default_endpoint_mode_dnsrr() -> None:
    """IPVS LXC workaround : endpoint_mode dnsrr toujours."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    assert spec["EndpointSpec"]["Mode"] == "dnsrr"


def test_build_service_spec_default_placement_manager() -> None:
    """Placement node.role==manager hardcoded (single-node manager MVP)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    constraints = spec["TaskTemplate"]["Placement"]["Constraints"]
    assert "node.role == manager" in constraints


def test_build_service_spec_default_replicas_one() -> None:
    """1 service = 1 agent (replicas:1 MVP)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    assert spec["Mode"] == {"Replicated": {"Replicas": 1}}


def test_build_service_spec_labels_on_container_and_service() -> None:
    """Labels agflow.* dupliquees au niveau container ET service."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="xyz789",
    )
    container_labels = spec["TaskTemplate"]["ContainerSpec"]["Labels"]
    service_labels = spec["Labels"]
    for labels in (container_labels, service_labels):
        assert labels["agflow.managed"] == "true"
        assert labels["agflow.dockerfile_id"] == "claude"
        assert labels["agflow.instance_id"] == "xyz789"


def test_build_service_spec_network_target() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    networks = spec["Networks"]
    assert any(n["Target"] == "agflow-internal" for n in networks)


def test_build_service_spec_restart_policy_on_failure() -> None:
    """RestartPolicy.Condition mappe vers 'on-failure' (best Swarm match)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    rp = spec["TaskTemplate"]["RestartPolicy"]
    assert rp["Condition"] == "on-failure"
    assert rp["MaxAttempts"] == 5
