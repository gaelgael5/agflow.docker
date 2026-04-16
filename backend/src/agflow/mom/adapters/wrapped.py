from __future__ import annotations

import json

from agflow.mom.adapters.generic import GenericAdapter
from agflow.mom.envelope import Kind, Route


class WrappedEntrypointAdapter(GenericAdapter):
    """Handles the `{task_id, type, data}` wrapper emitted by legacy
    entrypoint.sh scripts (aider, codex, mistral, …).

    `type=progress` → Kind.EVENT, data becomes payload.text (or re-parsed
    if data is itself a JSON object).
    `type=result`   → Kind.RESULT, data parsed as JSON (status, exit_code).
    Subclasses may override `_parse_inner_object` to add family-specific
    interpretation of structured payloads.
    """

    name: str = "wrapped"

    def parse_stdout_line(
        self,
        raw: str,
    ) -> tuple[Kind, dict, Route | None] | None:
        try:
            outer = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if not isinstance(outer, dict):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if "task_id" in outer and "type" in outer and "data" in outer:
            return self._parse_entrypoint_wrapper(outer)

        return super().parse_stdout_line(raw)

    def _parse_entrypoint_wrapper(
        self,
        outer: dict,
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
                if isinstance(inner, dict):
                    return self._parse_inner_object(inner)
            except (json.JSONDecodeError, ValueError):
                pass
            if data_raw:
                return Kind.EVENT, {"text": data_raw, "format": "raw"}, None
            return None

        return Kind.EVENT, {"text": str(data_raw), "format": "raw"}, None

    def _parse_inner_object(
        self,
        obj: dict,
    ) -> tuple[Kind, dict, Route | None] | None:
        """Override to interpret an inner object (e.g. vibe `role:...` messages).
        Default: treat as unknown structure, wrap as raw event."""
        return Kind.EVENT, {"text": json.dumps(obj, ensure_ascii=False), "format": "raw"}, None
