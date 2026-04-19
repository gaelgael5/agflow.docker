from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator


class Kind(StrEnum):
    INSTRUCTION = "instruction"
    CANCEL = "cancel"
    EVENT = "event"
    RESULT = "result"
    ERROR = "error"


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


_ROUTE_PREFIX_RE = re.compile(r"^(agent|team|pool|session):.+$")


class Route(BaseModel):
    target: str
    policy: str = "direct"

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if not _ROUTE_PREFIX_RE.match(v):
            raise ValueError(
                f"route.target must start with agent:|team:|pool:|session:, got '{v}'"
            )
        return v


class Envelope(BaseModel):
    v: int = 1
    msg_id: str
    parent_msg_id: str | None = None
    session_id: str
    instance_id: str
    direction: Direction
    timestamp: datetime = None  # type: ignore[assignment]
    source: str
    kind: Kind
    payload: dict
    route: Route | None = None

    def model_post_init(self, __context: object) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)
