"""Tests purs (pas de DB) pour ingest_creation_output : extraction des champs
1st-class depuis le JSON CreateLxcOutput vers le mapping DB."""
from __future__ import annotations

from agflow.schemas.infra import CreateLxcOutput
from agflow.services.infra_machines_service import (
    derive_machine_columns_from_output,
    derive_metadata_from_output,
)

_SAMPLE_JSON = {
    "status": "ok",
    "exit_code": 0,
    "identification": {"ctid": 300, "hostname": "swarm1-mgr", "hostname_raw": "swarm1-mgr"},
    "ressources": {"storage": "20G"},
    "systeme": {"distro": "debian-12", "ip": "192.168.10.300", "ip_type": "static"},
    "ssh_root": {"login_method": "key-only"},
    "users": [
        {"user": "agflow", "groups": ["sudo", "docker"], "sudo_nopasswd": True,
         "ssh_key_public": "ssh-ed25519 AAA..."},
    ],
    "docker": {"docker_ok": True, "docker_version": "29.4", "compose_version": "5.1",
               "hello_world_ok": True},
    "swarm": {"swarm_mode": "inactive", "swarm_ready": True, "tun_device_present": True},
    "host": {"proxmox_host": "pve", "script_version": "1.0",
             "conf_path": "/etc/pve/lxc/300.conf"},
}


def test_derive_machine_columns_extracts_1st_class_fields() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    cols = derive_machine_columns_from_output(out)

    assert cols["name"] == "swarm1-mgr"
    assert cols["host"] == "192.168.10.300"
    assert cols["username"] == "agflow"
    # IMPORTANT : la colonne DB s'appelle lxc_ctid (pas ctid, conflit systeme Postgres)
    assert cols["lxc_ctid"] == 300
    assert cols["distro"] == "debian-12"
    assert cols["ip_type"] == "static"
    assert cols["docker_version"] == "29.4"
    assert cols["compose_version"] == "5.1"
    assert cols["swarm_ready"] is True
    assert cols["swarm_mode"] == "inactive"
    assert cols["tun_device_present"] is True


def test_derive_machine_columns_status_ready_when_docker_ok_and_static_ip() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    cols = derive_machine_columns_from_output(out)
    assert cols["status"] == "ready"


def test_derive_machine_columns_status_partial_when_docker_not_ok() -> None:
    payload = {**_SAMPLE_JSON, "docker": {**_SAMPLE_JSON["docker"], "docker_ok": False}}
    out = CreateLxcOutput.model_validate(payload)
    cols = derive_machine_columns_from_output(out)
    assert cols["status"] == "partial"


def test_derive_metadata_includes_residual_fields() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    meta = derive_metadata_from_output(out)

    # Champs résiduels qui DOIVENT etre dans metadata
    assert meta["storage"] == "20G"
    assert meta["script_version"] == "1.0"
    assert meta["conf_path"] == "/etc/pve/lxc/300.conf"
    assert meta["agflow_user_groups"] == ["sudo", "docker"]
    assert meta["agflow_sudo_nopasswd"] is True
    assert meta["docker_hello_world_ok"] is True


def test_derive_metadata_does_not_include_1st_class_fields() -> None:
    """Defense contre la duplication : ce qui est en colonne ne doit pas etre en JSONB."""
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    meta = derive_metadata_from_output(out)

    # Aucun de ces fields ne doit etre dans metadata (ils sont en colonnes 1st-class)
    for forbidden in ["lxc_ctid", "ctid", "hostname", "ip", "ip_type", "distro",
                      "docker_version", "compose_version", "swarm_ready",
                      "swarm_mode", "tun_device_present"]:
        assert forbidden not in meta, f"{forbidden} doit etre en colonne, pas en metadata"
