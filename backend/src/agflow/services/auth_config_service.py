"""Singleton config pour l'authentification (mode local/keycloak + credentials)."""
from __future__ import annotations

from uuid import UUID

import structlog
from harpocrate.exceptions import VaultHttpError

from agflow.db.pool import execute, fetch_one
from agflow.schemas.auth_config import AuthConfigOut, AuthConfigUpdate
from agflow.services import harpocrate_vaults_service, vault_client

log = structlog.get_logger(__name__)

CLIENT_SECRET_PATH = "auth/keycloak/client_secret"


class InvalidUrlError(ValueError):
    """URL Keycloak invalide (ne commence pas par http:// ou https://)."""


class VaultNameUnknownError(LookupError):
    """vault_name fourni n'existe pas dans la table harpocrate_vaults.

    À ne pas confondre avec vault_client.VaultNotFoundError (coffre SDK absent).
    """


async def get_config() -> AuthConfigOut:
    """Lit la config en masquant le secret (juste has_secret: bool)."""
    row = await fetch_one(
        "SELECT mode, keycloak_url, keycloak_realm, keycloak_client_id, "
        "keycloak_client_secret_ref, vault_name, updated_at, updated_by_user_id "
        "FROM auth_config WHERE id = 1"
    )
    if row is None:
        raise RuntimeError("auth_config singleton missing — migration 113 not applied")
    return AuthConfigOut(
        mode=row["mode"],
        keycloak_url=row["keycloak_url"],
        keycloak_realm=row["keycloak_realm"],
        keycloak_client_id=row["keycloak_client_id"],
        has_secret=bool(row["keycloak_client_secret_ref"]),
        vault_name=row["vault_name"],
        updated_at=row["updated_at"],
        updated_by_user_id=row["updated_by_user_id"],
    )


async def get_config_internal() -> dict:
    """Lit la config avec la ref complète (usage interne : auth.py, test_connection).

    Retourne un dict pour ne pas leak la ref dans un type partagé avec l'API.
    """
    row = await fetch_one(
        "SELECT mode, keycloak_url, keycloak_realm, keycloak_client_id, "
        "keycloak_client_secret_ref, vault_name, updated_at, updated_by_user_id "
        "FROM auth_config WHERE id = 1"
    )
    if row is None:
        raise RuntimeError("auth_config singleton missing — migration 113 not applied")
    return dict(row)


async def update_config(
    payload: AuthConfigUpdate, *, actor_user_id: UUID | None
) -> AuthConfigOut:
    """Met à jour la config. Si keycloak_client_secret est fourni, le pousse
    dans Harpocrate avant de stocker la ref.
    """
    # Validation URL
    if (
        payload.keycloak_url is not None
        and payload.keycloak_url
        and not (
            payload.keycloak_url.startswith("http://")
            or payload.keycloak_url.startswith("https://")
        )
    ):
        raise InvalidUrlError(
            f"keycloak_url must start with http(s)://: {payload.keycloak_url!r}"
        )

    # Validation vault_name (si fourni)
    if payload.vault_name is not None:
        vault = await harpocrate_vaults_service.get_by_name(payload.vault_name)
        if vault is None:
            raise VaultNameUnknownError(payload.vault_name)

    # Push secret dans Harpocrate (si fourni en clair) — upsert
    new_ref: str | None = None
    if payload.keycloak_client_secret:
        target_vault = payload.vault_name
        if target_vault is None:
            current = await get_config_internal()
            target_vault = current["vault_name"]

        try:
            await vault_client.update_secret(
                CLIENT_SECRET_PATH,
                payload.keycloak_client_secret,
                vault_name=target_vault,
            )
        except VaultHttpError as exc:
            if exc.status_code == 404:
                await vault_client.create_secret(
                    CLIENT_SECRET_PATH,
                    payload.keycloak_client_secret,
                    description="Keycloak OIDC client_secret",
                    vault_name=target_vault,
                )
            else:
                raise
        new_ref = vault_client.build_ref(target_vault, CLIENT_SECRET_PATH)

    # UPDATE conditionnel
    sets: list[str] = []
    params: list[object] = []
    if payload.mode is not None:
        params.append(payload.mode)
        sets.append(f"mode = ${len(params)}")
    if payload.keycloak_url is not None:
        params.append(payload.keycloak_url)
        sets.append(f"keycloak_url = ${len(params)}")
    if payload.keycloak_realm is not None:
        params.append(payload.keycloak_realm)
        sets.append(f"keycloak_realm = ${len(params)}")
    if payload.keycloak_client_id is not None:
        params.append(payload.keycloak_client_id)
        sets.append(f"keycloak_client_id = ${len(params)}")
    if new_ref is not None:
        params.append(new_ref)
        sets.append(f"keycloak_client_secret_ref = ${len(params)}")
    if payload.vault_name is not None:
        params.append(payload.vault_name)
        sets.append(f"vault_name = ${len(params)}")
    params.append(actor_user_id)
    sets.append(f"updated_by_user_id = ${len(params)}")

    if sets:
        await execute(
            f"UPDATE auth_config SET {', '.join(sets)} WHERE id = 1", *params
        )

    log.info(
        "auth_config.updated",
        mode=payload.mode,
        keycloak_url=payload.keycloak_url,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )
    return await get_config()
