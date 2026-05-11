"""Ingestion des sorties create-swarm-lxc → colonnes et metadata infra_machines.

Fonctions pures (pas de DB, pas de vault) extraites d'infra_machines_service
pour maintenir la limite de 300 lignes du module principal.
"""
from __future__ import annotations

from typing import Any

from agflow.schemas.infra import CreateLxcOutput


def derive_machine_columns_from_output(output: CreateLxcOutput) -> dict[str, Any]:
    """Map le JSON CreateLxcOutput vers les colonnes typées de infra_machines.

    Ne retourne que les colonnes 1st-class (sans metadata). Le statut est
    dérivé : 'ready' si docker.docker_ok et systeme.ip_type valide, sinon
    'partial'. Note : la colonne DB s'appelle lxc_ctid (pas ctid, conflit
    avec colonne systeme Postgres) ; le champ JSON reste 'ctid'.
    """
    agflow_user = output.users[0] if output.users else None
    docker_ok = output.docker.docker_ok
    ip_type_valid = output.systeme.ip_type in ("static", "dhcp")
    return {
        "name": output.identification.hostname,
        "host": output.systeme.ip,
        "username": agflow_user.user if agflow_user else None,
        "lxc_ctid": output.identification.ctid,
        "distro": output.systeme.distro,
        "ip_type": output.systeme.ip_type,
        "docker_version": output.docker.docker_version,
        "compose_version": output.docker.compose_version,
        "swarm_ready": output.swarm.swarm_ready,
        "swarm_mode": output.swarm.swarm_mode,
        "tun_device_present": output.swarm.tun_device_present,
        "status": "ready" if (docker_ok and ip_type_valid) else "partial",
    }


def derive_metadata_from_output(output: CreateLxcOutput) -> dict[str, Any]:
    """Champs résiduels du JSON qui ne sont PAS en colonnes 1st-class.

    Utilisé pour peupler infra_machines.metadata (JSONB). Inclut le user
    agflow secondary metadata, les paths de conf, le hello_world_ok docker.
    """
    meta: dict[str, Any] = {}
    if output.ressources and "storage" in output.ressources:
        meta["storage"] = output.ressources["storage"]
    if output.host:
        if output.host.script_version is not None:
            meta["script_version"] = output.host.script_version
        if output.host.conf_path is not None:
            meta["conf_path"] = output.host.conf_path
        if output.host.conf_backup_path is not None:
            meta["conf_backup_path"] = output.host.conf_backup_path
    if output.users:
        agflow_user = output.users[0]
        meta["agflow_user_groups"] = list(agflow_user.groups)
        meta["agflow_sudo_nopasswd"] = agflow_user.sudo_nopasswd
    if output.docker.hello_world_ok is not None:
        meta["docker_hello_world_ok"] = output.docker.hello_world_ok
    return meta
