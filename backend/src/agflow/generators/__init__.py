from __future__ import annotations

from agflow.generators.base import GeneratedArtifact, Generator
from agflow.generators.docker_compose import DockerComposeGenerator
from agflow.generators.manual import ManualGenerator

GENERATORS: dict[str, type[Generator]] = {
    "docker_compose": DockerComposeGenerator,
    "manual": ManualGenerator,
}


def get_generator(name: str) -> Generator:
    cls = GENERATORS.get(name)
    if not cls:
        raise ValueError(f"Unknown generator: {name}. Available: {list(GENERATORS.keys())}")
    return cls()


__all__ = ["GeneratedArtifact", "Generator", "get_generator"]
