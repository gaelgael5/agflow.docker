"""Infrastructure certificates service — asyncpg CRUD + SSH key generation.

Private keys and passphrases are encrypted at rest via crypto_service (Fernet).
Supports RSA (4096 bits) and Ed25519 key generation.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.infra import CertificateSummary
from agflow.services import crypto_service

_log = structlog.get_logger(__name__)

_COLS = "id, name, key_type, private_key, public_key, passphrase, created_at, updated_at"


class CertificateNotFoundError(Exception):
    pass


def _to_summary(row: dict[str, Any]) -> CertificateSummary:
    return CertificateSummary(
        id=row["id"],
        name=row["name"],
        key_type=row.get("key_type", "rsa"),
        has_private_key=bool(row.get("private_key")),
        has_public_key=bool(row.get("public_key")),
        has_passphrase=bool(row.get("passphrase")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def generate_keypair(
    key_type: str = "rsa",
    passphrase: str | None = None,
) -> tuple[str, str]:
    """Generate an SSH key pair and return (private_pem, public_openssh)."""
    enc = serialization.BestAvailableEncryption(passphrase.encode()) if passphrase else serialization.NoEncryption()

    if key_type == "ed25519":
        private_key = ed25519.Ed25519PrivateKey.generate()
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=enc,
    ).decode()

    public_ssh = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()

    return private_pem, public_ssh


async def list_all() -> list[CertificateSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM infra_certificates ORDER BY name")
    return [_to_summary(r) for r in rows]


async def get_by_id(cert_id: UUID) -> CertificateSummary:
    row = await fetch_one(f"SELECT {_COLS} FROM infra_certificates WHERE id = $1", cert_id)
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")
    return _to_summary(row)


async def get_public_key(cert_id: UUID) -> str | None:
    """Return the public key (plain text). Derive from the private key if not stored."""
    row = await fetch_one(
        "SELECT public_key, private_key, passphrase FROM infra_certificates WHERE id = $1",
        cert_id,
    )
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")

    stored = row.get("public_key")
    if stored:
        return stored

    # Derive on the fly from the private key.
    encrypted_private = row.get("private_key")
    if not encrypted_private:
        return None
    try:
        priv_pem = crypto_service.decrypt(encrypted_private)
        passphrase_plain = crypto_service.decrypt(row.get("passphrase"))
        priv_bytes = priv_pem.encode()
        pwd = passphrase_plain.encode() if passphrase_plain else None
        private_key = serialization.load_ssh_private_key(priv_bytes, password=pwd)
        public_ssh = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ).decode()
        return public_ssh
    except Exception as exc:
        _log.warning("infra_certificates.derive_public_key_failed", id=str(cert_id), error=str(exc))
        return None


async def get_decrypted(cert_id: UUID) -> dict[str, Any]:
    """Return certificate with decrypted private key (for SSH use)."""
    row = await fetch_one(f"SELECT {_COLS} FROM infra_certificates WHERE id = $1", cert_id)
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")
    return {
        "id": row["id"],
        "name": row["name"],
        "private_key": crypto_service.decrypt(row["private_key"]),
        "public_key": row["public_key"],
        "passphrase": crypto_service.decrypt(row["passphrase"]),
    }


async def create(
    name: str,
    private_key: str,
    public_key: str | None = None,
    passphrase: str | None = None,
    key_type: str = "rsa",
) -> CertificateSummary:
    row = await fetch_one(
        f"""
        INSERT INTO infra_certificates (name, key_type, private_key, public_key, passphrase)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING {_COLS}
        """,
        name,
        key_type,
        crypto_service.encrypt(private_key),
        public_key,
        crypto_service.encrypt(passphrase),
    )
    assert row is not None
    _log.info("infra_certificates.create", name=name, key_type=key_type)
    return _to_summary(row)


async def generate(
    name: str,
    key_type: str = "rsa",
    passphrase: str | None = None,
) -> tuple[CertificateSummary, str]:
    """Generate a new SSH key pair, store it, return (summary, public_key)."""
    private_pem, public_ssh = generate_keypair(key_type, passphrase)
    summary = await create(
        name=name,
        private_key=private_pem,
        public_key=public_ssh,
        passphrase=passphrase,
        key_type=key_type,
    )
    return summary, public_ssh


async def update(cert_id: UUID, **kwargs: Any) -> CertificateSummary:
    await get_by_id(cert_id)

    updates: dict[str, Any] = {}
    for field in ("name", "private_key", "public_key", "passphrase"):
        if field in kwargs and kwargs[field] is not None:
            val = kwargs[field]
            if field in ("private_key", "passphrase"):
                val = crypto_service.encrypt(val)
            updates[field] = val

    if not updates:
        return await get_by_id(cert_id)

    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    row = await fetch_one(
        f"UPDATE infra_certificates SET {', '.join(sets)} WHERE id = $1 RETURNING {_COLS}",
        cert_id, *updates.values(),
    )
    assert row is not None
    _log.info("infra_certificates.update", id=str(cert_id))
    return _to_summary(row)


async def delete(cert_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM infra_certificates WHERE id = $1 RETURNING id", cert_id,
    )
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")
    _log.info("infra_certificates.delete", id=str(cert_id))
