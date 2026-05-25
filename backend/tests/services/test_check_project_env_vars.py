# backend/tests/services/test_check_project_env_vars.py
"""Tests d'intégration de check_project_env_vars (DB réelle, LXC 201)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.db.pool import execute
from agflow.services import infra_env_vars_service as svc
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _seed_minimal_project_with_via_env_script(*, input_value: str) -> dict:
    """Crée un projet + groupe + group_script avec UNE variable via_env qui pointe sur `input_value`.

    Retourne les IDs créés pour assertions.
    """
    # Catégorie + named_type + machine
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'machine-target', $2, '127.0.0.1', 22)",
        m_id,
        nt_id,
    )

    # Projet + groupe
    p_id = uuid.uuid4()
    await execute(
        "INSERT INTO projects (id, display_name) VALUES ($1, 'proj-test')",
        p_id,
    )
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'primary', 1, 1, $3)",
        g_id,
        p_id,
        m_id,
    )

    # Script avec input via_env
    s_id = uuid.uuid4()
    input_vars = [
        {"name": "KC_ADMIN_PASSWORD", "description": "", "default": "", "via_env": True},
    ]
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 'create-oidc-client', '', 'echo {KC_ADMIN_PASSWORD}', $2)",
        s_id,
        json.dumps(input_vars),
    )

    # group_script reliant le tout, input_values = {KC_ADMIN_PASSWORD: input_value}
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id,
        g_id,
        s_id,
        m_id,
        json.dumps({"KC_ADMIN_PASSWORD": input_value}),
    )
    return {
        "project_id": p_id,
        "group_id": g_id,
        "script_id": s_id,
        "gs_id": gs_id,
        "machine_id": m_id,
    }


async def test_check_returns_no_missing_when_input_value_is_env_machine_ref(fresh_db) -> None:
    """Le bug fixé : ${env-machine://X:VAR} doit être reconnu comme couvrant la variable."""
    # Setup : machine X = keycloak1, variable KC_ADMIN_PASSWORD avec value non-vide
    await execute("INSERT INTO infra_categories (name) VALUES ('cat-kc') ON CONFLICT DO NOTHING")
    nt_kc = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat-kc', 'SSH')",
        nt_kc,
    )
    kc_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'keycloak1', $2, '127.0.0.1', 22)",
        kc_id,
        nt_kc,
    )
    ev_id = uuid.uuid4()
    await execute(
        "INSERT INTO named_type_env_vars (id, named_type_id, name) "
        "VALUES ($1, $2, 'KC_ADMIN_PASSWORD')",
        ev_id,
        nt_kc,
    )
    await execute(
        "INSERT INTO infra_machine_env_vars (machine_id, named_type_env_var_id, value) "
        "VALUES ($1, $2, 's3cret')",
        kc_id,
        ev_id,
    )

    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
    )

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 0
    assert result.items == []


async def test_check_reports_machine_not_found(fresh_db) -> None:
    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env-machine://ghost-machine:KC_ADMIN_PASSWORD}",
    )

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 1
    assert len(result.items) == 1
    item = result.items[0]
    assert len(item.missing) == 1
    assert item.missing[0].kind == "machine_not_found"
    assert item.missing[0].var_name == "KC_ADMIN_PASSWORD"
    assert "ghost-machine" in item.missing[0].detail


async def test_check_reports_empty_value(fresh_db) -> None:
    seed = await _seed_minimal_project_with_via_env_script(input_value="")

    result = await svc.check_project_env_vars(seed["project_id"])

    assert result.total_missing == 1
    assert result.items[0].missing[0].kind == "value_empty"


async def test_check_skips_scripts_without_via_env(fresh_db) -> None:
    """Si toutes les inputs sont via_env=false, le script est ignoré."""
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'm', $2, '127.0.0.1', 22)",
        m_id,
        nt_id,
    )
    p_id = uuid.uuid4()
    await execute("INSERT INTO projects (id, display_name) VALUES ($1, 'p')", p_id)
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'g', 1, 1, $3)",
        g_id,
        p_id,
        m_id,
    )
    s_id = uuid.uuid4()
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 's', '', '', $2)",
        s_id,
        json.dumps([{"name": "X", "via_env": False, "default": "", "description": ""}]),
    )
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id,
        g_id,
        s_id,
        m_id,
        json.dumps({"X": ""}),
    )

    result = await svc.check_project_env_vars(p_id)
    assert result.total_missing == 0


async def test_check_skips_group_script_with_deployment_host_no_machine(fresh_db) -> None:
    """target_kind=deployment_host sans machine assignee au groupe -> silencieusement skippe."""
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    p_id = uuid.uuid4()
    await execute("INSERT INTO projects (id, display_name) VALUES ($1, 'p')", p_id)
    g_id = uuid.uuid4()
    # Groupe SANS machine_id (NULL valide : groups.machine_id est nullable)
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas) "
        "VALUES ($1, $2, 'g', 1, 1)",
        g_id,
        p_id,
    )
    s_id = uuid.uuid4()
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 's', '', '', $2)",
        s_id,
        json.dumps([{"name": "X", "via_env": True, "default": "", "description": ""}]),
    )
    gs_id = uuid.uuid4()
    # target_kind=deployment_host : machine resolue depuis le groupe (NULL ici -> leve)
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'deployment_host', $4)",
        gs_id,
        g_id,
        s_id,
        json.dumps({"X": "${env-machine://m:V}"}),
    )

    result = await svc.check_project_env_vars(p_id)
    # Le group_script est silencieusement skippe (resolve_target_machine_id leve)
    assert result.total_missing == 0
    assert result.items == []


async def test_check_no_missing_when_input_value_is_env_ref_resolvable(fresh_db) -> None:
    """${env://NAME} couverte par platform_secret avec value non vide -> no missing."""
    # Insere une entree platform_secrets : key = '${env://API_TOKEN}', default_value = valeur
    await execute(
        "INSERT INTO platform_secrets (key, default_value) VALUES ($1, $2)",
        "${env://API_TOKEN}",
        "tok-123",
    )
    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env://API_TOKEN}",
    )
    result = await svc.check_project_env_vars(seed["project_id"])
    assert result.total_missing == 0
    assert result.items == []


async def test_check_reports_env_ref_when_platform_secret_missing(fresh_db) -> None:
    """${env://NAME} avec NAME inexistant -> platform_secret_missing."""
    seed = await _seed_minimal_project_with_via_env_script(
        input_value="${env://NO_SUCH_VAR}",
    )
    result = await svc.check_project_env_vars(seed["project_id"])
    assert result.total_missing == 1
    item = result.items[0]
    assert len(item.missing) == 1
    assert item.missing[0].kind == "platform_secret_missing"
    assert "NO_SUCH_VAR" in item.missing[0].detail


async def test_check_aggregates_multiple_reasons_in_one_script(fresh_db) -> None:
    """Un script avec 2 via_env, l'une OK et l'autre KO, doit lister UNE raison."""
    await execute("INSERT INTO infra_categories (name) VALUES ('cat') ON CONFLICT DO NOTHING")
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'NT', 'cat', 'SSH')",
        nt_id,
    )
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'm', $2, '127.0.0.1', 22)",
        m_id,
        nt_id,
    )
    p_id = uuid.uuid4()
    await execute("INSERT INTO projects (id, display_name) VALUES ($1, 'p')", p_id)
    g_id = uuid.uuid4()
    await execute(
        "INSERT INTO groups (id, project_id, name, max_agents, max_replicas, machine_id) "
        "VALUES ($1, $2, 'g', 1, 1, $3)",
        g_id,
        p_id,
        m_id,
    )
    s_id = uuid.uuid4()
    inputs = [
        {"name": "OK_VAR", "via_env": True, "default": "", "description": ""},
        {"name": "KO_VAR", "via_env": True, "default": "", "description": ""},
    ]
    await execute(
        "INSERT INTO scripts (id, name, description, content, input_variables) "
        "VALUES ($1, 's', '', '', $2)",
        s_id,
        json.dumps(inputs),
    )
    gs_id = uuid.uuid4()
    await execute(
        "INSERT INTO group_scripts (id, group_id, script_id, position, timing, "
        "target_kind, machine_id, input_values) "
        "VALUES ($1, $2, $3, 0, 'before', 'fixed_machine', $4, $5)",
        gs_id,
        g_id,
        s_id,
        m_id,
        json.dumps({"OK_VAR": "literal-ok", "KO_VAR": ""}),
    )

    result = await svc.check_project_env_vars(p_id)
    assert result.total_missing == 1
    assert len(result.items) == 1
    assert len(result.items[0].missing) == 1
    assert result.items[0].missing[0].var_name == "KO_VAR"
    assert result.items[0].missing[0].kind == "value_empty"
