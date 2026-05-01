"""Tests pour _generate_tmp_files_swarm() + run_task_swarm()."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override AGFLOW_DATA_DIR vers tmp_path pour test isolation."""
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGFLOW_DATA_HOST_DIR", str(tmp_path))
    # Crée le sous-dir attendu pour le dockerfile
    (tmp_path / "dockerfiles" / "claude").mkdir(parents=True)
    return tmp_path


def test_generate_tmp_files_swarm_creates_4_files(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {
        "Image": "agflow-claude:abc",
        "Env": ["KEY=val"],
        "HostConfig": {"Memory": 1073741824, "NanoCpus": 1500000000, "Binds": []},
        "Labels": {"agflow.managed": "true", "agflow.dockerfile_id": "claude",
                   "agflow.instance_id": "xyz"},
    }
    deploy_path = _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="agent-claude-xyz",
        config=config,
        task_payload={"text": "hello"},
    )

    tmp_dir = tmp_data_dir / "dockerfiles" / "claude" / ".tmp"
    assert tmp_dir.exists()
    assert (tmp_dir / ".env").exists()
    assert (tmp_dir / "stack.yml").exists()
    assert (tmp_dir / "deploy.sh").exists()
    assert (tmp_dir / "task.json").exists()
    assert deploy_path == str(tmp_dir / "deploy.sh")


def test_generate_tmp_files_swarm_stack_yml_is_valid_compose(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {
        "Image": "agflow-claude:abc",
        "Env": ["KEY=val"],
        "HostConfig": {"Memory": 1073741824, "Binds": []},
        "Labels": {"agflow.managed": "true"},
    }
    _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="agent-claude-xyz",
        config=config,
        task_payload={"text": "hi"},
    )

    stack_yml = (tmp_data_dir / "dockerfiles" / "claude" / ".tmp" / "stack.yml").read_text()
    parsed = yaml.safe_load(stack_yml)

    assert "services" in parsed
    assert "agent" in parsed["services"]
    svc = parsed["services"]["agent"]
    assert svc["image"] == "agflow-claude:abc"
    # Doit contenir le bloc deploy avec endpoint_mode dnsrr + placement manager
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert "node.role == manager" in svc["deploy"]["placement"]["constraints"]
    # Restart policy 'none' pour one-shot
    assert svc["deploy"]["restart_policy"]["condition"] == "none"
    # Network agflow-internal external
    assert parsed["networks"]["agflow-internal"]["external"] is True


def test_generate_tmp_files_swarm_task_json_is_payload(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {"Image": "img", "Env": [], "HostConfig": {"Binds": []}, "Labels": {}}
    _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="x",
        config=config,
        task_payload={"key": "value", "nested": {"a": 1}},
    )

    task_json = (tmp_data_dir / "dockerfiles" / "claude" / ".tmp" / "task.json").read_text()
    parsed = json.loads(task_json)
    assert parsed == {"key": "value", "nested": {"a": 1}}


def test_generate_tmp_files_swarm_deploy_sh_is_executable(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {"Image": "img", "Env": [], "HostConfig": {"Binds": []}, "Labels": {}}
    deploy_path = _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="x",
        config=config,
        task_payload={"k": "v"},
    )
    # Vérifie le shebang + structure attendue
    content = Path(deploy_path).read_text()
    assert content.startswith("#!/usr/bin/env bash")
    assert "docker stack deploy" in content
    assert "docker service logs" in content
    assert "docker stack rm" in content
    # Sur Unix, vérifie le mode exécutable. Sur Windows, skipped.
    if os.name != "nt":
        assert os.access(deploy_path, os.X_OK)


@pytest.mark.asyncio
async def test_run_task_swarm_yields_done_event_on_success(tmp_data_dir: Path) -> None:
    """run_task_swarm doit yield au moins un event 'done' avec status."""
    from agflow.services import container_runner

    # Mock subprocess pour simuler bash deploy.sh qui ouvre, stream, ferme
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout.readline = AsyncMock(side_effect=[
        b'{"type":"log","data":"hello"}\n',
        b"",  # EOF
    ])
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    params = """
    {
      "docker": {
        "Container": {"Name": "agent-claude-{id}", "Image": "agflow-claude:{hash}"},
        "Network": {"Mode": "agflow-internal"},
        "Runtime": {"Init": true, "WorkingDir": "/app"},
        "Resources": {"Memory": "1g"},
        "Environments": {},
        "Mounts": []
      },
      "Params": {}
    }
    """

    with (
        patch("agflow.services.container_runner._load_platform_secrets",
              AsyncMock(return_value={})),
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=[])),
        patch("agflow.services.container_runner._ensure_mount_paths_from_config"),
        patch("asyncio.create_subprocess_exec",
              AsyncMock(return_value=fake_proc)),
    ):
        events = []
        async for ev in container_runner.run_task_swarm(
            dockerfile_id="claude",
            params_json_content=params,
            content_hash="abc",
            task_payload={"text": "hello"},
            cleanup=True,
        ):
            events.append(ev)

    # Au moins un event 'done' avec status success/failure
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["status"] == "success"
    assert done_events[0]["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_task_swarm_rejects_when_max_services_reached(tmp_data_dir: Path) -> None:
    """Concurrency guard : MAX_RUNNING_CONTAINERS encore enforced."""
    from agflow.services import container_runner

    fake_alive = [
        container_runner.ContainerInfo(
            id=f"c{i}", name=f"n{i}", dockerfile_id="x", image="i",
            status="running", created_at="2026-01-01T00:00:00", instance_id="i",
        )
        for i in range(container_runner.MAX_RUNNING_CONTAINERS)
    ]
    with (
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=fake_alive)),
        pytest.raises(container_runner.TooManyContainersError),
    ):
        params = """
        {"docker": {"Container": {"Name": "x", "Image": "y"},
         "Network": {}, "Runtime": {}, "Resources": {},
         "Environments": {}, "Mounts": []}, "Params": {}}
        """
        async for _ in container_runner.run_task_swarm(
            dockerfile_id="claude",
            params_json_content=params,
            content_hash="abc",
            task_payload={},
        ):
            pass
