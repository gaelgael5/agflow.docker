"""Pure-function tests for project_runtimes_service helpers (no DB)."""
from __future__ import annotations

from uuid import UUID

from agflow.services.project_runtimes_service import (
    _normalize_state,
    _parse_docker_ports,
    runtime_short_id,
    user_network_name,
)


class TestUserNetworkName:
    def test_uses_first_8_hex_of_user_id(self) -> None:
        uid = UUID("a3f1b2c4-1111-2222-3333-444455556666")
        assert user_network_name(uid) == "agflow-user-a3f1b2c4"


class TestRuntimeShortId:
    def test_uses_first_8_hex(self) -> None:
        rid = UUID("12345678-9abc-def0-1234-567890abcdef")
        assert runtime_short_id(rid) == "12345678"


class TestParseDockerPorts:
    def test_simple_mapping(self) -> None:
        # Single host->container mapping
        result = _parse_docker_ports("0.0.0.0:32785->9000/tcp")
        assert result == [{"container": 9000, "host": 32785, "protocol": "tcp"}]

    def test_dual_stack_dedup(self) -> None:
        # Same port exposed on IPv4 and IPv6 — should appear once
        result = _parse_docker_ports(
            "0.0.0.0:32785->9000/tcp, [::]:32785->9000/tcp",
        )
        assert result == [{"container": 9000, "host": 32785, "protocol": "tcp"}]

    def test_multiple_ports(self) -> None:
        result = _parse_docker_ports(
            "0.0.0.0:32785->9000/tcp, 0.0.0.0:32786->9001/tcp",
        )
        assert {"container": 9000, "host": 32785, "protocol": "tcp"} in result
        assert {"container": 9001, "host": 32786, "protocol": "tcp"} in result
        assert len(result) == 2

    def test_unmapped_container_port(self) -> None:
        # Container port exposed without host bind
        result = _parse_docker_ports("9000/tcp")
        assert result == [{"container": 9000, "protocol": "tcp"}]

    def test_default_protocol_tcp(self) -> None:
        # No /tcp suffix → default to tcp
        result = _parse_docker_ports("0.0.0.0:32785->9000")
        assert result == [{"container": 9000, "host": 32785, "protocol": "tcp"}]

    def test_udp_protocol_preserved(self) -> None:
        result = _parse_docker_ports("0.0.0.0:5353->5353/udp")
        assert result == [{"container": 5353, "host": 5353, "protocol": "udp"}]

    def test_empty(self) -> None:
        assert _parse_docker_ports("") == []

    def test_garbage_skipped(self) -> None:
        # Malformed pieces should be silently skipped, valid ones kept
        result = _parse_docker_ports("invalid, 0.0.0.0:32785->9000/tcp, also-bad")
        assert result == [{"container": 9000, "host": 32785, "protocol": "tcp"}]


class TestNormalizeState:
    def test_running(self) -> None:
        assert _normalize_state("running") == "running"
        assert _normalize_state("Up 2 hours") == "running"

    def test_stopped(self) -> None:
        assert _normalize_state("exited") == "stopped"
        assert _normalize_state("Exited (0) 5 minutes ago") == "stopped"
        assert _normalize_state("stopped") == "stopped"

    def test_created(self) -> None:
        assert _normalize_state("created") == "created"

    def test_restarting(self) -> None:
        assert _normalize_state("restarting") == "restarting"

    def test_unknown_returns_lowered(self) -> None:
        assert _normalize_state("WeirdState") == "weirdstate"

    def test_empty_returns_unknown(self) -> None:
        assert _normalize_state("") == "unknown"
