from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.user_secrets import UserSecretSummary, VaultStatus

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultAlreadyInitializedError(Exception):
    pass


class VaultNotInitializedError(Exception):
    pass


class SecretNotFoundError(Exception):
    pass


class DuplicateSecretError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_secret(row: dict[str, Any]) -> UserSecretSummary:
    return UserSecretSummary(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        ciphertext=row["ciphertext"],
        iv=row["iv"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Vault management
# ---------------------------------------------------------------------------


async def get_vault_status(user_id: UUID) -> VaultStatus:
    row = await fetch_one(
        "SELECT vault_salt, vault_test_ciphertext, vault_test_iv FROM users WHERE id = $1",
        user_id,
    )
    if row is None:
        return VaultStatus(initialized=False)
    return VaultStatus(
        initialized=row["vault_salt"] is not None,
        salt=row["vault_salt"],
        test_ciphertext=row["vault_test_ciphertext"],
        test_iv=row["vault_test_iv"],
    )


async def setup_vault(
    user_id: UUID,
    salt: str,
    test_ciphertext: str,
    test_iv: str,
) -> None:
    row = await fetch_one(
        "SELECT vault_salt FROM users WHERE id = $1",
        user_id,
    )
    if row is not None and row["vault_salt"] is not None:
        raise VaultAlreadyInitializedError(f"Vault already initialized for user {user_id}")
    await execute(
        """
        UPDATE users
        SET vault_salt = $2, vault_test_ciphertext = $3, vault_test_iv = $4
        WHERE id = $1
        """,
        user_id,
        salt,
        test_ciphertext,
        test_iv,
    )
    _log.info("vault.setup", user_id=str(user_id))


async def change_vault_passphrase(
    user_id: UUID,
    salt: str,
    test_ciphertext: str,
    test_iv: str,
    re_encrypted: list[dict[str, Any]],
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE users
                SET vault_salt = $2, vault_test_ciphertext = $3, vault_test_iv = $4
                WHERE id = $1
                """,
                user_id,
                salt,
                test_ciphertext,
                test_iv,
            )
            for item in re_encrypted:
                await conn.execute(
                    """
                    UPDATE user_secrets
                    SET ciphertext = $2, iv = $3, updated_at = NOW()
                    WHERE id = $1 AND user_id = $4
                    """,
                    item["id"],
                    item["ciphertext"],
                    item["iv"],
                    user_id,
                )
    _log.info("vault.change_passphrase", user_id=str(user_id), count=len(re_encrypted))


# ---------------------------------------------------------------------------
# Secret CRUD
# ---------------------------------------------------------------------------


async def list_secrets(user_id: UUID) -> list[UserSecretSummary]:
    rows = await fetch_all(
        "SELECT id, user_id, name, ciphertext, iv, created_at, updated_at FROM user_secrets WHERE user_id = $1 ORDER BY name ASC",
        user_id,
    )
    return [_row_to_secret(r) for r in rows]


async def create_secret(
    user_id: UUID,
    name: str,
    ciphertext: str,
    iv: str,
) -> UserSecretSummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO user_secrets (user_id, name, ciphertext, iv)
            VALUES ($1, $2, $3, $4)
            RETURNING id, user_id, name, ciphertext, iv, created_at, updated_at
            """,
            user_id,
            name,
            ciphertext,
            iv,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateSecretError(f"Secret '{name}' already exists for user {user_id}") from exc
    assert row is not None
    _log.info("secret.create", user_id=str(user_id), name=name)
    return _row_to_secret(row)


async def update_secret(
    secret_id: UUID,
    user_id: UUID,
    ciphertext: str,
    iv: str,
) -> UserSecretSummary:
    row = await fetch_one(
        """
        UPDATE user_secrets
        SET ciphertext = $3, iv = $4, updated_at = NOW()
        WHERE id = $1 AND user_id = $2
        RETURNING id, user_id, name, ciphertext, iv, created_at, updated_at
        """,
        secret_id,
        user_id,
        ciphertext,
        iv,
    )
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found for user {user_id}")
    _log.info("secret.update", secret_id=str(secret_id), user_id=str(user_id))
    return _row_to_secret(row)


async def delete_secret(secret_id: UUID, user_id: UUID) -> None:
    result = await execute(
        "DELETE FROM user_secrets WHERE id = $1 AND user_id = $2",
        secret_id,
        user_id,
    )
    if result == "DELETE 0":
        raise SecretNotFoundError(f"Secret {secret_id} not found for user {user_id}")
    _log.info("secret.delete", secret_id=str(secret_id), user_id=str(user_id))
