from __future__ import annotations

import json

from agflow.mom.adapters.generic import GenericAdapter
from agflow.mom.adapters.mistral import MistralAdapter
from agflow.mom.adapters.wrapped import WrappedEntrypointAdapter
from agflow.mom.envelope import Direction, Envelope, Kind


def _make_envelope(**overrides) -> Envelope:
    defaults = dict(
        msg_id="aaa-bbb", session_id="s1", instance_id="i1",
        direction=Direction.IN, source="test", kind=Kind.INSTRUCTION,
        payload={"text": "hello"},
    )
    return Envelope(**(defaults | overrides))


class TestGenericAdapter:
    def test_format_stdin_produces_json(self) -> None:
        adapter = GenericAdapter()
        env = _make_envelope()
        raw = adapter.format_stdin(env)
        parsed = json.loads(raw)
        assert parsed["payload"]["text"] == "hello"
        assert parsed["msg_id"] == "aaa-bbb"

    def test_parse_valid_json_with_kind(self) -> None:
        adapter = GenericAdapter()
        line = json.dumps({"kind": "event", "payload": {"text": "progress"}})
        kind, payload, route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert payload["text"] == "progress"
        assert route is None

    def test_parse_raw_text(self) -> None:
        adapter = GenericAdapter()
        kind, payload, _route = adapter.parse_stdout_line("just some text")
        assert kind == Kind.EVENT
        assert payload["text"] == "just some text"
        assert payload["format"] == "raw"

    def test_parse_json_without_kind_wraps_raw(self) -> None:
        adapter = GenericAdapter()
        kind, payload, _route = adapter.parse_stdout_line('{"foo": "bar"}')
        assert kind == Kind.EVENT
        assert payload["format"] == "raw"

    def test_parse_extracts_route_to(self) -> None:
        adapter = GenericAdapter()
        line = json.dumps({
            "kind": "instruction",
            "payload": {"text": "delegate"},
            "route_to": "agent:other",
        })
        _kind, payload, route = adapter.parse_stdout_line(line)
        assert route is not None
        assert route.target == "agent:other"
        assert "route_to" not in payload


class TestMistralAdapter:
    def test_skip_system_role(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({"role": "system", "content": "big system prompt"})
        result = adapter.parse_stdout_line(line)
        assert result is None

    def test_skip_user_role(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({"role": "user", "content": "user prompt"})
        result = adapter.parse_stdout_line(line)
        assert result is None

    def test_assistant_content(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({
            "role": "assistant",
            "content": "Hello world",
            "message_id": "m1",
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert payload["text"] == "Hello world"
        assert payload["format"] == "mistral.vibe/v1"
        assert payload["data"]["role"] == "assistant"

    def test_assistant_with_tool_calls(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "grep"}}],
            "message_id": "m2",
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert "[tool:grep]" in payload["text"]

    def test_tool_role(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({
            "role": "tool",
            "content": "found 3 matches",
            "tool_call_id": "tc1",
            "message_id": "m3",
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert "found 3 matches" in payload["text"]

    def test_empty_assistant_skipped(self) -> None:
        adapter = MistralAdapter()
        line = json.dumps({
            "role": "assistant",
            "content": "",
            "tool_calls": None,
            "message_id": "m4",
        })
        result = adapter.parse_stdout_line(line)
        assert result is None

    def test_non_json_wraps_raw(self) -> None:
        adapter = MistralAdapter()
        kind, payload, _route = adapter.parse_stdout_line("plain error text")
        assert kind == Kind.EVENT
        assert payload["format"] == "raw"

    def test_entrypoint_wrapper_line(self) -> None:
        adapter = MistralAdapter()
        inner = json.dumps({"role": "assistant", "content": "hi", "message_id": "m5"})
        wrapper = json.dumps({
            "task_id": "t1",
            "type": "progress",
            "data": inner,
        })
        kind, payload, _route = adapter.parse_stdout_line(wrapper)
        assert kind == Kind.EVENT
        assert payload["text"] == "hi"

    def test_entrypoint_result_line(self) -> None:
        adapter = MistralAdapter()
        wrapper = json.dumps({
            "task_id": "t1",
            "type": "result",
            "data": json.dumps({"status": "success", "exit_code": 0}),
        })
        kind, payload, _route = adapter.parse_stdout_line(wrapper)
        assert kind == Kind.RESULT
        assert payload["status"] == "success"


class TestWrappedEntrypointAdapter:
    def test_aider_progress_line(self) -> None:
        adapter = WrappedEntrypointAdapter()
        line = json.dumps({
            "task_id": "t1",
            "type": "progress",
            "data": "Aider: applied 3 changes",
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert payload["text"] == "Aider: applied 3 changes"
        assert payload["format"] == "raw"

    def test_codex_result_line(self) -> None:
        adapter = WrappedEntrypointAdapter()
        line = json.dumps({
            "task_id": "t1",
            "type": "result",
            "data": json.dumps({"status": "failure", "exit_code": 2}),
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.RESULT
        assert payload["status"] == "failure"
        assert payload["exit_code"] == 2

    def test_non_wrapper_falls_back_to_generic(self) -> None:
        adapter = WrappedEntrypointAdapter()
        kind, payload, _route = adapter.parse_stdout_line("plain text")
        assert kind == Kind.EVENT
        assert payload["format"] == "raw"

    def test_inner_object_wraps_raw_by_default(self) -> None:
        adapter = WrappedEntrypointAdapter()
        inner = json.dumps({"foo": "bar", "baz": 42})
        line = json.dumps({
            "task_id": "t1",
            "type": "progress",
            "data": inner,
        })
        kind, payload, _route = adapter.parse_stdout_line(line)
        assert kind == Kind.EVENT
        assert payload["format"] == "raw"
