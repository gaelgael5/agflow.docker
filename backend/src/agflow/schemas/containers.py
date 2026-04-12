from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ContainerStatus = Literal[
    "created", "running", "restarting", "removing", "paused", "exited", "dead"
]


class ContainerInfo(BaseModel):
    id: str
    name: str
    dockerfile_id: str
    image: str
    status: ContainerStatus
    created_at: datetime
    instance_id: str
