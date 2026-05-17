"""CRUD de la table hmac_keys (callbacks HMAC pour workflows).

Stockage : secret_hex chiffré au repos via Fernet (clé = settings.harpocrate_dek).
"""
from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

import asyncpg
import structlog
from cryptography.fernet import Fernet, InvalidToken

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_one

_log = structlog.get_logger(__name__)


class DuplicateHmacKeyError(Exception):
    pass


class HmacKeyNotFoundError(Exception):
    pass


def _fernet() -> Fernet:
    """Dérive une clé Fernet à partir de settings.harpocrate_dek."""
    dek = get_settings().harpocrate_dek
    if not dek:
        raise RuntimeError(
            "harpocrate_dek non configurée — hmac_keys nécessite cette clé"
        )
    derived = urlsafe_b64encode(sha256(dek.encode()).digest())
    return Fernet(derived)


async def create(
    *, key_id: str, secret_hex: str, description: str = ""
) -> None:
    fernet = _fernet()
    encrypted = fernet.encrypt(secret_hex.encode())
    try:
        await execute(
            """
            INSERT INTO hmac_keys (key_id, key_value_encrypted, description)
            VALUES ($1, $2, $3)
            """,
            key_id,
            encrypted,
            description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateHmacKeyError(f"key_id '{key_id}' already exists") from exc
    _log.info("workflow.hmac_key.created", key_id=key_id)


async def get_by_key_id(key_id: str) -> dict | None:
    row = await fetch_one(
        """
        SELECT key_id, key_value_encrypted, description, created_at
        FROM hmac_keys
        WHERE key_id = $1
        """,
        key_id,
    )
    if row is None:
        return None
    fernet = _fernet()
    try:
        secret_hex = fernet.decrypt(bytes(row["key_value_encrypted"])).decode()
    except InvalidToken as exc:
        _log.error("workflow.hmac_key.decrypt_failed", key_id=key_id)
        raise RuntimeError(f"hmac key '{key_id}' decryption failed") from exc
    return {
        "key_id": row["key_id"],
        "secret_hex": secret_hex,
        "description": row["description"],
        "created_at": row["created_at"],
    }


async def exists(key_id: str) -> bool:
    row = await fetch_one(
        "SELECT 1 FROM hmac_keys WHERE key_id = $1 AND rotated_at IS NULL",
        key_id,
    )
    return row is not None
