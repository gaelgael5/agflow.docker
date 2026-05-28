# backend/src/agflow/services/infra_env_vars_service.py
"""Variables d'environnement infra — CRUD contrat (named_type) + implémentation (machine).

Migration 121. Résolution des refs via platform_secrets_service.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra_env_vars import (
    MachineEnvVarRow,
    MachineSecretEntry,
    NamedTypeEnvVarRow,
    ProjectEnvVarsCheck,
    ProjectEnvVarsCheckMissing,
)

_log = structlog.get_logger(__name__)


class EnvVarNotFoundError(Exception):
    pass


class EnvVarDuplicateError(Exception):
    pass


class EnvVarForeignKeyError(ValueError):
    """named_type_env_var_id n'appartient pas à la variante de la machine."""


# ── helpers ─────────────────────────────────────────────────────────────────


def _to_nt_row(row: dict[str, Any]) -> NamedTypeEnvVarRow:
    return NamedTypeEnvVarRow(
        id=row["id"],
        named_type_id=row["named_type_id"],
        name=row["name"],
        description=row.get("description", ""),
        position=row.get("position", 0),
        is_secret=row.get("is_secret", False),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_machine_row(row: dict[str, Any]) -> MachineEnvVarRow:
    return MachineEnvVarRow(
        id=row["id"],
        machine_id=row["machine_id"],
        named_type_env_var_id=row["named_type_env_var_id"],
        name=row["name"],
        description=row.get("description", ""),
        value=row.get("value", ""),
        is_secret=row.get("is_secret", False),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _upsert_vault_secret(
    existing_ref: str | None,
    path: str,
    new_value: str,
    vault_name: str,
) -> str:
    """Garantit que `path` contient `new_value` dans le coffre ; retourne le vault ref."""
    from agflow.services import vault_client

    parsed = vault_client.parse_ref(existing_ref) if existing_ref else None
    if parsed is not None:
        existing_vault, existing_path = parsed
        if existing_vault == vault_name and existing_path == path:
            await vault_client.update_secret(path, new_value, vault_name=vault_name)
        else:
            await vault_client.create_secret(path, new_value, vault_name=vault_name)
            try:
                await vault_client.delete_secret(existing_path, vault_name=existing_vault)
            except Exception:
                _log.warning(
                    "infra_env_vars.vault_cleanup_failed",
                    vault=existing_vault,
                    path=existing_path,
                )
    else:
        await vault_client.create_secret(path, new_value, vault_name=vault_name)
    return vault_client.build_ref(vault_name, path)


# ── named_type env vars CRUD ─────────────────────────────────────────────────


async def list_by_named_type(named_type_id: UUID) -> list[NamedTypeEnvVarRow]:
    rows = await fetch_all(
        "SELECT id, named_type_id, name, description, position, is_secret, created_at, updated_at "
        "FROM infra_named_type_env_vars WHERE named_type_id = $1 ORDER BY position, name",
        named_type_id,
    )
    return [_to_nt_row(r) for r in rows]


async def get_env_var_by_id(env_var_id: UUID) -> NamedTypeEnvVarRow:
    row = await fetch_one(
        "SELECT id, named_type_id, name, description, position, is_secret, created_at, updated_at "
        "FROM infra_named_type_env_vars WHERE id = $1",
        env_var_id,
    )
    if row is None:
        raise EnvVarNotFoundError(f"env_var {env_var_id} not found")
    return _to_nt_row(row)


async def create_env_var(
    named_type_id: UUID,
    name: str,
    description: str = "",
    position: int = 0,
    is_secret: bool = False,
) -> NamedTypeEnvVarRow:
    import asyncpg

    try:
        row = await fetch_one(
            "INSERT INTO infra_named_type_env_vars "
            "  (named_type_id, name, description, position, is_secret) "
            "VALUES ($1, $2, $3, $4, $5) "
            "RETURNING id, named_type_id, name, description, position, is_secret, created_at, updated_at",
            named_type_id,
            name,
            description,
            position,
            is_secret,
        )
    except asyncpg.UniqueViolationError as exc:
        raise EnvVarDuplicateError(
            f"env_var {name!r} already exists for named_type {named_type_id}"
        ) from exc
    assert row is not None  # RETURNING garantit une ligne si pas d'exception
    _log.info("infra_env_vars.create", named_type_id=str(named_type_id), name=name)
    return _to_nt_row(row)


async def update_env_var(
    env_var_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    position: int | None = None,
    is_secret: bool | None = None,
) -> NamedTypeEnvVarRow:
    import asyncpg

    current = await get_env_var_by_id(env_var_id)
    next_name = name if name is not None else current.name
    next_description = description if description is not None else current.description
    next_position = position if position is not None else current.position
    next_is_secret = is_secret if is_secret is not None else current.is_secret
    try:
        row = await fetch_one(
            "UPDATE infra_named_type_env_vars "
            "SET name = $2, description = $3, position = $4, is_secret = $5 "
            "WHERE id = $1 "
            "RETURNING id, named_type_id, name, description, position, is_secret, created_at, updated_at",
            env_var_id,
            next_name,
            next_description,
            next_position,
            next_is_secret,
        )
    except asyncpg.UniqueViolationError as exc:
        raise EnvVarDuplicateError(f"another env_var already uses the name {next_name!r}") from exc
    assert row is not None  # RETURNING garantit une ligne si pas d'exception
    _log.info("infra_env_vars.update", id=str(env_var_id), name=next_name)
    return _to_nt_row(row)


async def delete_env_var(env_var_id: UUID) -> None:
    await get_env_var_by_id(env_var_id)
    result = await execute(
        "DELETE FROM infra_named_type_env_vars WHERE id = $1",
        env_var_id,
    )
    if result.endswith(" 0"):
        raise EnvVarNotFoundError(f"env_var {env_var_id} not found")
    _log.info("infra_env_vars.delete", id=str(env_var_id))


# ── machine env vars ─────────────────────────────────────────────────────────


async def list_machine_env_vars(machine_id: UUID) -> list[MachineEnvVarRow]:
    """Retourne toutes les env vars du contrat de la machine (valeur vide si non remplie)."""
    rows = await fetch_all(
        """
        SELECT
            coalesce(mv.id, gen_random_uuid()) AS id,
            $1::uuid                           AS machine_id,
            nv.id                              AS named_type_env_var_id,
            nv.name,
            nv.description,
            nv.is_secret,
            coalesce(mv.value, '')             AS value,
            coalesce(mv.created_at, now())     AS created_at,
            coalesce(mv.updated_at, now())     AS updated_at
        FROM infra_machines m
        JOIN infra_named_type_env_vars nv ON nv.named_type_id = m.type_id
        LEFT JOIN infra_machine_env_vars mv
               ON mv.machine_id = $1 AND mv.named_type_env_var_id = nv.id
        WHERE m.id = $1
        ORDER BY nv.position, nv.name
        """,
        machine_id,
    )
    return [_to_machine_row(r) for r in rows]


async def upsert_machine_env_vars(
    machine_id: UUID,
    values: dict[UUID, str],
    secrets: dict[UUID, MachineSecretEntry] | None = None,
) -> list[MachineEnvVarRow]:
    """Upsert atomique des valeurs + secrets vault. Lève EnvVarForeignKeyError si un ID est inconnu."""
    secrets = secrets or {}

    if not values and not secrets:
        return await list_machine_env_vars(machine_id)

    # Vérifier que tous les IDs appartiennent au contrat de la machine
    all_ids = set(values.keys()) | set(secrets.keys())
    valid_ids = {
        r["id"]
        for r in await fetch_all(
            """
            SELECT nv.id FROM infra_named_type_env_vars nv
            JOIN infra_machines m ON m.type_id = nv.named_type_id
            WHERE m.id = $1
            """,
            machine_id,
        )
    }
    unknown = all_ids - valid_ids
    if unknown:
        raise EnvVarForeignKeyError(
            f"env_var ids {unknown} do not belong to machine {machine_id}'s named_type"
        )

    # Résoudre les secrets : stocker dans le coffre, récupérer le vault ref
    final_values = dict(values)
    for ev_id, entry in secrets.items():
        path = f"env-vars/{machine_id}/{ev_id}"
        existing_row = await fetch_one(
            "SELECT value FROM infra_machine_env_vars "
            "WHERE machine_id = $1 AND named_type_env_var_id = $2",
            machine_id,
            ev_id,
        )
        existing_ref = existing_row["value"] if existing_row else None
        ref = await _upsert_vault_secret(existing_ref, path, entry.value, entry.vault_name)
        final_values[ev_id] = ref

    from agflow.db.pool import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        for ev_id, val in final_values.items():
            await conn.execute(
                """
                INSERT INTO infra_machine_env_vars
                    (machine_id, named_type_env_var_id, value)
                VALUES ($1, $2, $3)
                ON CONFLICT (machine_id, named_type_env_var_id)
                DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                machine_id,
                ev_id,
                val,
            )

    _log.info(
        "infra_env_vars.upsert_machine",
        machine_id=str(machine_id),
        count=len(final_values),
        secrets_count=len(secrets),
    )
    return await list_machine_env_vars(machine_id)


async def resolve_for_machine(machine_id: UUID) -> dict[str, str]:
    """Retourne {name: valeur_résolue} pour la machine. Exclut les valeurs vides après résolution."""
    from agflow.services import platform_secrets_service, vault_client

    secrets_map = await platform_secrets_service.resolve_all()
    rows = await list_machine_env_vars(machine_id)
    result: dict[str, str] = {}
    for row in rows:
        value = row.value
        if not value:
            continue
        parsed = vault_client.parse_ref(value)
        if parsed:
            vault_name, path = parsed
            try:
                resolved: str | None = await vault_client.get_secret(path, vault_name=vault_name)
            except Exception:
                resolved = None
        else:
            resolved = platform_secrets_service.resolve_platform_refs(value, secrets_map) or None
        if resolved:
            result[row.name] = resolved
    return result


# ── project env vars check ────────────────────────────────────────────────────


async def check_project_env_vars(project_id: UUID) -> ProjectEnvVarsCheck:
    """Pour chaque group_script avec via_env, dry-run du resolver et rapport.

    Utilise input_resolver.resolve_input_values_collect : on n'arrête pas
    au 1er échec, on accumule toutes les raisons.

    Une via_env var dont l'input_value se résout (ou est couverte par la
    machine cible / les group_variables) → absente de `missing`.
    Sinon → entrée dans `missing` avec le `kind` typé.
    """
    from agflow.schemas.infra_env_vars import ProjectEnvVarsCheckMissingReason
    from agflow.services import (
        group_scripts_service,
        group_variables_service,
        groups_service,
        input_resolver,
        platform_secrets_service,
        scripts_service,
    )

    groups = await groups_service.list_by_project(project_id)
    platform_secrets_map = await platform_secrets_service.resolve_all()
    items: list[ProjectEnvVarsCheckMissing] = []

    for group in groups:
        group_vars = await group_variables_service.list_by_group(group.id)
        env_text = "\n".join(f"{v.name}={v.value}" for v in group_vars if v.value)
        group_var_names = {v.name for v in group_vars if v.value}

        group_scripts = await group_scripts_service.list_by_group(group.id)
        for gs in group_scripts:
            script = await scripts_service.get_by_id(gs.script_id)
            via_env_vars = [v for v in script.input_variables if v.via_env]
            if not via_env_vars:
                continue

            # Résoudre la machine cible (conserve la logique existante)
            machine_id: UUID | None = None
            machine_name: str | None = gs.machine_name or None
            if gs.target_kind == "fixed_machine" and gs.machine_id:
                machine_id = gs.machine_id
            elif gs.target_kind == "deployment_host":
                try:
                    machine_id = await group_scripts_service.resolve_target_machine_id(gs.id)
                except Exception as exc:
                    _log.debug(
                        "infra_env_vars.check.skip_group_script",
                        gs_id=str(gs.id),
                        reason=str(exc),
                    )
                    continue
            if machine_id is None:
                continue

            # Construire les input_values sur la base des via_env vars du script.
            # Si l'input_value est absent du group_script, on le considère comme
            # value_empty (le user n'a rien saisi).
            via_env_names = {v.name for v in via_env_vars}
            relevant_inputs = {
                k: v for k, v in (gs.input_values or {}).items() if k in via_env_names
            }
            for v in via_env_vars:
                if v.name not in relevant_inputs:
                    relevant_inputs[v.name] = ""

            _, errors = await input_resolver.resolve_input_values_collect(
                input_values=relevant_inputs,
                env_text=env_text,
                platform_secrets_map=platform_secrets_map,
            )

            # Filtre : si une via_env var est déjà couverte par une group_variable
            # non vide, on retire son erreur du rapport.
            reasons: list[ProjectEnvVarsCheckMissingReason] = [
                ProjectEnvVarsCheckMissingReason(
                    var_name=err.var_name or "<unknown>",
                    kind=err.kind,
                    ref=err.ref,
                    detail=err.detail,
                )
                for err in errors
                if (err.var_name or "") not in group_var_names
            ]
            if reasons:
                items.append(
                    ProjectEnvVarsCheckMissing(
                        group_script_id=gs.id,
                        script_id=script.id,
                        script_name=script.name,
                        group_id=group.id,
                        group_name=group.name,
                        machine_id=machine_id,
                        machine_name=machine_name,
                        target_kind=gs.target_kind,
                        missing=reasons,
                    )
                )

    return ProjectEnvVarsCheck(
        project_id=project_id,
        total_missing=sum(len(it.missing) for it in items),
        items=items,
    )
