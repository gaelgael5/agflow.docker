from __future__ import annotations

import json

from agflow.mom.adapters.wrapped import WrappedEntrypointAdapter
from agflow.mom.envelope import Kind, Route


class MistralAdapter(WrappedEntrypointAdapter):
    name: str = "mistral"

    def parse_stdout_line(
        self,
        raw: str,
    ) -> tuple[Kind, dict, Route | None] | None:
        # Mistral vibe can emit role-messages WITHOUT the wrapper too
        # (depends on the entrypoint variant). Handle both paths.
        try:
            outer = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if isinstance(outer, dict) and "role" in outer and "task_id" not in outer:
            return self._parse_inner_object(outer)

        return super().parse_stdout_line(raw)

    def _parse_inner_object(
        self,
        msg: dict,
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
