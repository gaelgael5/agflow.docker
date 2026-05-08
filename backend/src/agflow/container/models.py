from __future__ import annotations

from enum import StrEnum


class RuntimeMode(StrEnum):
    DOCKER_STANDALONE = "docker_standalone"
    DOCKER_SWARM = "docker_swarm"
    CONTAINERD = "containerd"
    K3S = "k3s"
    K8S = "k8s"
    NONE = "none"
