from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GeneratedArtifact:
    filename: str
    content: str
    artifact_type: str = "file"


class Generator(Protocol):
    name: str

    def generate(
        self,
        recipe: dict[str, Any],
        instance_name: str,
        resolved_secrets: dict[str, str],
        resolved_variables: dict[str, str],
        options: dict[str, Any] | None = None,
    ) -> list[GeneratedArtifact]: ...
