from __future__ import annotations

import json

from agflow.mom.adapters.generic import GenericAdapter
from agflow.mom.envelope import Kind, Route


class MistralAdapter(GenericAdapter):
    name: str = "mistral"

    def parse_stdout_line(
        self, raw: str,
    ) -> tuple[Kind, dict, Route | None] | None:
        try:
            outer = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if not isinstance(outer, dict):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if "task_id" in outer and "type" in outer and "data" in outer:
            return self._parse_entrypoint_wrapper(outer)

        if "role" in outer:
            return self._parse_vibe_message(outer)

        return super().parse_stdout_line(raw)

    def _parse_entrypoint_wrapper(
        self, outer: dict,
    ) -> tuple[Kind, dict, Route | None] | None:
        msg_type = outer.get("type")
        data_raw = outer.get("data", "")

        if msg_type == "result":
            try:
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
            except (json.JSONDecodeError, ValueError):
                data = {"status": "unknown", "raw": data_raw}
            return Kind.RESULT, data, None

        if isinstance(data_raw, str):
            try:
                inner = json.loads(data_raw)
                if isinstance(inner, dict) and "role" in inner:
                    return self._parse_vibe_message(inner)
            except (json.JSONDecodeError, ValueError):
                pass
            if data_raw:
                return Kind.EVENT, {"text": data_raw, "format": "raw"}, None
            return None

        return Kind.EVENT, {"text": str(data_raw), "format": "raw"}, None

    def _parse_vibe_message(
        self, msg: dict,
    ) -> tuple[Kind, dict, Route | None] | None:
        role = msg.get("role", "")

        if role in ("system", "user"):
            return None

        route_to = msg.pop("route_to", None)
        route = Route(target=route_to) if route_to else None

        if role == "assistant":
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            tc_names = [
                f"[tool:{tc.get('function', {}).get('name', '?')}]"
                for tc in tool_calls
            ]
            text = content
            if tc_names:
                text = (content + " " + " ".join(tc_names)).strip()
            if not text:
                return None
            return Kind.EVENT, {
                "text": text,
                "data": msg,
                "format": "mistral.vibe/v1",
                "message_id": msg.get("message_id"),
            }, route

        if role == "tool":
            return Kind.EVENT, {
                "text": str(msg.get("content", ""))[:500],
                "data": msg,
                "format": "mistral.vibe/v1/tool_result",
                "tool_call_id": msg.get("tool_call_id"),
                "message_id": msg.get("message_id"),
            }, route

        return Kind.EVENT, {"text": str(msg), "format": "raw"}, route
