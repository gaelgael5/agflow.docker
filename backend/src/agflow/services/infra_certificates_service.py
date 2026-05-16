"""Infrastructure certificates service — asyncpg CRUD + SSH key generation.

Les clés privées et passphrases sont stockées dans Harpocrate ; les colonnes
DB `private_key` / `passphrase` conservent un vault ref
(`${vault://HARPOCRATE_KEY:certificates/<id>/<part>}`).

Supporte RSA (4096 bits) et Ed25519.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import CertificateSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)

_COLS = "id, name, key_type, private_key, public_key, passphrase, created_at, updated_at"

_VAULT_REF_RE = re.compile(r"^\$\{vault://([^:]+):(.+)\}$")
_VAULT_KEY_NAME = "HARPOCRATE_KEY"


# ── Vault helpers ────────────────────────────────────────────────────────


def _vault_path_private_key(cert_id: UUID) -> str:
    return f"certificates/{cert_id}/private_key"


def _vault_path_passphrase(cert_id: UUID) -> str:
    return f"certificates/{cert_id}/passphrase"


def _vault_ref(path: str) -> str:
    return f"${{vault://{_VAULT_KEY_NAME}:{path}}}"


def _parse_vault_ref(value: str | None) -> str | None:
    """Retourne le chemin vault si value est un vault ref valide, sinon None."""
    if not value:
        return None
    m = _VAULT_REF_RE.match(value)
    return m.group(2) if (m and m.group(1) == _VAULT_KEY_NAME) else None


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
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )

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
    row = await fetch_one(
        f"SELECT {_COLS} FROM infra_certificates WHERE id = $1", cert_id,
    )
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")
    return _to_summary(row)


async def _read_secret(value: str | None) -> str | None:
    """Si value est un vault ref, fetch dans Harpocrate ; sinon retourne tel quel.

    Le fallback (retour brut) couvre les lignes héritées avant migration ;
    en pratique, après ce refactor toute valeur non-NULL doit être un ref.
    """
    if value is None:
        return None
    path = _parse_vault_ref(value)
    if path is None:
        return value
    return await vault_client.get_secret(path)


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

    # Dériver à la volée depuis la clé privée stockée dans le vault.
    encrypted_private = row.get("private_key")
    if not encrypted_private:
        return None
    try:
        priv_pem = await _read_secret(encrypted_private)
        passphrase_plain = await _read_secret(row.get("passphrase"))
        if not priv_pem:
            return None
        pwd = passphrase_plain.encode() if passphrase_plain else None
        private_key = serialization.load_ssh_private_key(priv_pem.encode(), password=pwd)
        return private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ).decode()
    except Exception as exc:
        _log.warning(
            "infra_certificates.derive_public_key_failed",
            id=str(cert_id), error=str(exc),
        )
        return None


async def get_decrypted(cert_id: UUID) -> dict[str, Any]:
    """Return certificate with decrypted private key (for SSH use)."""
    row = await fetch_one(
        f"SELECT {_COLS} FROM infra_certificates WHERE id = $1", cert_id,
    )
    if row is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")
    return {
        "id": row["id"],
        "name": row["name"],
        "private_key": await _read_secret(row["private_key"]),
        "public_key": row["public_key"],
        "passphrase": await _read_secret(row["passphrase"]),
    }


async def create(
    name: str,
    private_key: str,
    public_key: str | None = None,
    passphrase: str | None = None,
    key_type: str = "rsa",
) -> CertificateSummary:
    """Crée un certificat. La clé privée et la passphrase sont stockées dans Harpocrate.

    Les colonnes DB `private_key` / `passphrase` sont NOT NULL pour private_key
    (cf. migration 001) : on génère l'id en Python, on push les secrets dans
    Harpocrate, puis on fait un seul INSERT avec les vault refs.
    """
    cert_id = uuid4()
    created_paths: list[str] = []
    try:
        priv_path = _vault_path_private_key(cert_id)
        await vault_client.create_secret(priv_path, private_key)
        created_paths.append(priv_path)
        priv_ref = _vault_ref(priv_path)

        pass_ref: str | None = None
        if passphrase is not None:
            pass_path = _vault_path_passphrase(cert_id)
            await vault_client.create_secret(pass_path, passphrase)
            created_paths.append(pass_path)
            pass_ref = _vault_ref(pass_path)

        row = await fetch_one(
            f"""
            INSERT INTO infra_certificates
                (id, name, key_type, private_key, public_key, passphrase)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {_COLS}
            """,
            cert_id, name, key_type, priv_ref, public_key, pass_ref,
        )
        assert row is not None
    except Exception:
        for path in created_paths:
            try:
                await vault_client.delete_secret(path)
            except Exception:
                _log.warning("infra_certificates.vault_rollback_failed", path=path)
        raise

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


async def _upsert_vault_secret(existing_value: str | None, path: str, new_value: str) -> str:
    """Garantit que le secret `path` contient `new_value` ; retourne le vault ref."""
    existing_path = _parse_vault_ref(existing_value)
    if existing_path == path:
        await vault_client.update_secret(path, new_value)
    elif existing_path:
        # Cas pathologique : ref vers un autre path. On bascule sur le path canonique.
        await vault_client.create_secret(path, new_value)
        try:
            await vault_client.delete_secret(existing_path)
        except Exception:
            _log.warning("infra_certificates.vault_cleanup_failed", path=existing_path)
    else:
        await vault_client.create_secret(path, new_value)
    return _vault_ref(path)


async def update(cert_id: UUID, **kwargs: Any) -> CertificateSummary:
    await get_by_id(cert_id)

    new_private_key = kwargs.pop("private_key", None)
    new_passphrase = kwargs.pop("passphrase", None)

    if new_private_key is not None or new_passphrase is not None:
        existing = await fetch_one(
            "SELECT private_key, passphrase FROM infra_certificates WHERE id = $1",
            cert_id,
        )
        assert existing is not None

        if new_private_key is not None:
            ref = await _upsert_vault_secret(
                existing["private_key"], _vault_path_private_key(cert_id), new_private_key,
            )
            await execute(
                "UPDATE infra_certificates SET private_key = $1 WHERE id = $2",
                ref, cert_id,
            )

        if new_passphrase is not None:
            ref = await _upsert_vault_secret(
                existing["passphrase"], _vault_path_passphrase(cert_id), new_passphrase,
            )
            await execute(
                "UPDATE infra_certificates SET passphrase = $1 WHERE id = $2",
                ref, cert_id,
            )

    updates: dict[str, Any] = {}
    for field in ("name", "public_key"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if updates:
        sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
        await execute(
            f"UPDATE infra_certificates SET {', '.join(sets)} WHERE id = $1",
            cert_id, *updates.values(),
        )

    _log.info("infra_certificates.update", id=str(cert_id))
    return await get_by_id(cert_id)


async def delete(cert_id: UUID) -> None:
    existing = await fetch_one(
        "SELECT private_key, passphrase FROM infra_certificates WHERE id = $1",
        cert_id,
    )
    if existing is None:
        raise CertificateNotFoundError(f"Certificate {cert_id} not found")

    paths = [
        p for p in (
            _parse_vault_ref(existing["private_key"]),
            _parse_vault_ref(existing["passphrase"]),
        )
        if p
    ]

    await execute("DELETE FROM infra_certificates WHERE id = $1", cert_id)

    for path in paths:
        try:
            await vault_client.delete_secret(path)
        except Exception:
            _log.warning(
                "infra_certificates.vault_delete_failed",
                id=str(cert_id), path=path,
            )

    _log.info("infra_certificates.delete", id=str(cert_id))
