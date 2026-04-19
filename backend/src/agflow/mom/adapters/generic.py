from __future__ import annotations

import json

from agflow.mom.envelope import Envelope, Kind, Route


class GenericAdapter:
    name: str = "generic"

    def format_stdin(self, envelope: Envelope) -> bytes:
        data = {
            "msg_id": envelope.msg_id,
            "payload": envelope.payload,
            "source": envelope.source,
            "kind": str(envelope.kind),
        }
        return (json.dumps(data, ensure_ascii=False) + "\n").encode()

    def parse_stdout_line(
        self, raw: str,
    ) -> tuple[Kind, dict, Route | None] | None:
        route: Route | None = None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        if not isinstance(parsed, dict):
            return Kind.EVENT, {"text": raw, "format": "raw"}, None

        route_to = parsed.pop("route_to", None)
        if route_to:
            route = Route(target=route_to)

        raw_kind = parsed.get("kind")
        raw_payload = parsed.get("payload")
        if raw_kind and raw_payload and isinstance(raw_payload, dict):
            try:
                kind = Kind(raw_kind)
                return kind, raw_payload, route
            except ValueError:
                pass

        return Kind.EVENT, {"text": raw, "format": "raw"}, route
