"""Pure-function tests for compose_renderer_service runtime helpers (no DB)."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from agflow.services.compose_renderer_service import _build_runtime_instance_ctx


def _make_instance(name: str = "test-inst", variables: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        instance_name=name,
        variables=variables or {},
    )


def _recipe(*service_ids: str) -> dict:
    return {
        "services": [
            {"id": svc_id, "ports": [9000 + i]}
            for i, svc_id in enumerate(service_ids)
        ],
    }


class TestBuildRuntimeInstanceCtx:
    def test_replica_0_no_suffix_for_unindexed_form(self) -> None:
        # When replica_count = 1, the renderer also strips the suffix from
        # service hostnames; the ctx exposes both forms for reverse
        # compatibility with recipes that don't know about replicas.
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(),
            recipe=_recipe("minio", "whisper"),
            replica_index=0,
            rt_short="abc12345",
        )
        # Same-replica ref (with index suffix)
        assert ctx["services.minio.host"] == "rt_abc12345_minio_0"
        # Cross-replica/unindexed ref (used when replica_count == 1 and the
        # recipe wrote {{ services.X.host }} without thinking about replicas).
        assert ctx["services.minio.host_unindexed"] == "rt_abc12345_minio"
        assert ctx["services.whisper.host"] == "rt_abc12345_whisper_0"

    def test_replica_index_propagated(self) -> None:
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(),
            recipe=_recipe("minio"),
            replica_index=2,
            rt_short="abc12345",
        )
        assert ctx["replica_index"] == "2"
        assert ctx["services.minio.host"] == "rt_abc12345_minio_2"

    def test_user_vars_passed_through(self) -> None:
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(variables={"DOMAIN": "example.com", "NUM": 42}),
            recipe=_recipe("app"),
            replica_index=0,
            rt_short="aaaaaaaa",
        )
        assert ctx["DOMAIN"] == "example.com"
        # int → str conversion
        assert ctx["NUM"] == "42"

    def test_none_user_vars_skipped(self) -> None:
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(variables={"VALID": "x", "NULLED": None}),
            recipe=_recipe("app"),
            replica_index=0,
            rt_short="aaaaaaaa",
        )
        assert ctx["VALID"] == "x"
        assert "NULLED" not in ctx

    def test_port_propagated(self) -> None:
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(),
            recipe=_recipe("minio"),
            replica_index=0,
            rt_short="aaaaaaaa",
        )
        # First port of the service is exposed as services.X.port
        assert ctx["services.minio.port"] == "9000"

    def test_instance_metadata_present(self) -> None:
        ctx = _build_runtime_instance_ctx(
            inst=_make_instance(name="prod-tools"),
            recipe=_recipe("app"),
            replica_index=0,
            rt_short="aaaaaaaa",
        )
        assert ctx["instance_name"] == "prod-tools"
        assert ctx["_name"] == "prod-tools"
        assert "instance_id" in ctx
