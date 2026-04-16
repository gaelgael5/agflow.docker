from __future__ import annotations

from typing import Protocol

from agflow.mom.envelope import Envelope, Kind, Route


class AgentAdapter(Protocol):
    name: str

    def format_stdin(self, envelope: Envelope) -> bytes: ...

    def parse_stdout_line(
        self, raw: str,
    ) -> tuple[Kind, dict, Route | None] | None: ...
