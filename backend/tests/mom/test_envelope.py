from __future__ import annotations

import pytest

from agflow.mom.envelope import Direction, Envelope, Kind, Route


class TestKind:
    def test_valid_kinds(self) -> None:
        assert Kind.INSTRUCTION == "instruction"
        assert Kind.CANCEL == "cancel"
        assert Kind.EVENT == "event"
        assert Kind.RESULT == "result"
        assert Kind.ERROR == "error"


class TestDirection:
    def test_in_out(self) -> None:
        assert Direction.IN == "in"
        assert Direction.OUT == "out"


class TestRoute:
    def test_route_with_target(self) -> None:
        r = Route(target="agent:abc-123")
        assert r.target == "agent:abc-123"
        assert r.policy == "direct"

    def test_route_rejects_empty_target(self) -> None:
        with pytest.raises(ValueError):
            Route(target="")

    def test_route_rejects_unknown_prefix(self) -> None:
        with pytest.raises(ValueError):
            Route(target="unknown:abc")

    def test_route_accepts_all_valid_prefixes(self) -> None:
        for prefix in ("agent:", "team:", "pool:", "session:"):
            r = Route(target=f"{prefix}test-id")
            assert r.target.startswith(prefix)


class TestEnvelope:
    def test_minimal_envelope(self) -> None:
        env = Envelope(
            msg_id="a1b2c3d4-0000-0000-0000-000000000000",
            session_id="sess-1",
            instance_id="inst-1",
            direction=Direction.OUT,
            source="system",
            kind=Kind.EVENT,
            payload={"text": "hello"},
        )
        assert env.v == 1
        assert env.parent_msg_id is None
        assert env.route is None
        assert env.payload == {"text": "hello"}

    def test_envelope_with_route_and_parent(self) -> None:
        env = Envelope(
            msg_id="a1b2c3d4-0000-0000-0000-000000000000",
            parent_msg_id="e5f6a7b8-0000-0000-0000-000000000000",
            session_id="sess-1",
            instance_id="inst-1",
            direction=Direction.IN,
            source="agent:tech-lead",
            kind=Kind.INSTRUCTION,
            payload={"text": "fix this"},
            route=Route(target="agent:specialist-1"),
        )
        assert env.parent_msg_id == "e5f6a7b8-0000-0000-0000-000000000000"
        assert env.route is not None
        assert env.route.target == "agent:specialist-1"

    def test_envelope_rejects_invalid_kind(self) -> None:
        with pytest.raises(ValueError):
            Envelope(
                msg_id="a1",
                session_id="s",
                instance_id="i",
                direction=Direction.IN,
                source="x",
                kind="bogus",
                payload={},
            )

    def test_envelope_to_dict_roundtrip(self) -> None:
        env = Envelope(
            msg_id="a1b2c3d4-0000-0000-0000-000000000000",
            session_id="sess-1",
            instance_id="inst-1",
            direction=Direction.OUT,
            source="system",
            kind=Kind.EVENT,
            payload={"text": "hello"},
        )
        d = env.model_dump(mode="json")
        env2 = Envelope.model_validate(d)
        assert env2 == env
