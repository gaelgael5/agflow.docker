"""Infrastructure certificates service — asyncpg CRUD + SSH key generation.

Les clés privées et passphrases sont stockées dans Harpocrate ; les colonnes
DB `private_key` / `passphrase` conservent un vault ref portant le nom logique
du coffre cible (cf. `harpocrate_vaults`) :

    ${vault://<vault_name>:certificates/<id>/<part>}

Supporte RSA (4096 bits) et Ed25519.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra import CertificateSummary
from agflow.services import harpocrate_vaults_service, vault_client

_log = structlog.get_logger(__name__)

_COLS = "id, name, key_type, private_key, public_key, passphrase, created_at, updated_at"


# ── Vault helpers ────────────────────────────────────────────────────────


def _path_private_key(cert_id: UUID) -> str:
    return f"certificates/{cert_id}/private_key"


def _path_passphrase(cert_id: UUID) -> str:
    return f"certificates/{cert_id}/passphrase"


async def _require_default_vault_name() -> str:
    """Résout le nom du coffre Harpocrate par défaut. Lève si aucun configuré."""
    default = await harpocrate_vaults_service.get_default()
    if default is None:
        raise vault_client.VaultNotFoundError(
            "No default Harpocrate vault configured — see /settings"
        )
    return default.name


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
    """Si value est un vault ref, fetch depuis Harpocrate (en routant vers le
    coffre nommé dans le ref). Sinon retourne la valeur telle quelle.
    """
    if value is None:
        return None
    if vault_client.parse_ref(value) is None:
        return value
    return await vault_client.resolve_ref(value)


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
    """Crée un certificat. Les secrets vivent dans le coffre Harpocrate par défaut."""
    vault_name = await _require_default_vault_name()
    cert_id = uuid4()
    created_paths: list[str] = []
    try:
        priv_path = _path_private_key(cert_id)
        await vault_client.create_secret(priv_path, private_key, vault_name=vault_name)
        created_paths.append(priv_path)
        priv_ref = vault_client.build_ref(vault_name, priv_path)

        pass_ref: str | None = None
        if passphrase is not None:
            pass_path = _path_passphrase(cert_id)
            await vault_client.create_secret(pass_path, passphrase, vault_name=vault_name)
            created_paths.append(pass_path)
            pass_ref = vault_client.build_ref(vault_name, pass_path)

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
                await vault_client.delete_secret(path, vault_name=vault_name)
            except Exception:
                _log.warning("infra_certificates.vault_rollback_failed", path=path)
        raise

    _log.info("infra_certificates.create", name=name, key_type=key_type, vault=vault_name)
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


async def _upsert_vault_secret(
    existing_ref: str | None, path: str, new_value: str, vault_name: str,
) -> str:
    """Garantit que `path` contient `new_value` dans le coffre courant ; retourne le ref."""
    parsed = vault_client.parse_ref(existing_ref) if existing_ref else None
    if parsed is not None:
        existing_vault, existing_path = parsed
        if existing_vault == vault_name and existing_path == path:
            await vault_client.update_secret(path, new_value, vault_name=vault_name)
        else:
            # Cas pathologique : ref vers un autre path/coffre. On bascule vers le ref canonique.
            await vault_client.create_secret(path, new_value, vault_name=vault_name)
            try:
                await vault_client.delete_secret(existing_path, vault_name=existing_vault)
            except Exception:
                _log.warning(
                    "infra_certificates.vault_cleanup_failed",
                    vault=existing_vault, path=existing_path,
                )
    else:
        await vault_client.create_secret(path, new_value, vault_name=vault_name)
    return vault_client.build_ref(vault_name, path)


async def update(cert_id: UUID, **kwargs: Any) -> CertificateSummary:
    await get_by_id(cert_id)

    new_private_key = kwargs.pop("private_key", None)
    new_passphrase = kwargs.pop("passphrase", None)

    if new_private_key is not None or new_passphrase is not None:
        vault_name = await _require_default_vault_name()
        existing = await fetch_one(
            "SELECT private_key, passphrase FROM infra_certificates WHERE id = $1",
            cert_id,
        )
        assert existing is not None

        if new_private_key is not None:
            ref = await _upsert_vault_secret(
                existing["private_key"], _path_private_key(cert_id),
                new_private_key, vault_name,
            )
            await execute(
                "UPDATE infra_certificates SET private_key = $1 WHERE id = $2",
                ref, cert_id,
            )

        if new_passphrase is not None:
            ref = await _upsert_vault_secret(
                existing["passphrase"], _path_passphrase(cert_id),
                new_passphrase, vault_name,
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

    refs_to_purge: list[tuple[str, str]] = []  # (vault_name, path)
    for raw in (existing["private_key"], existing["passphrase"]):
        parsed = vault_client.parse_ref(raw)
        if parsed is not None:
            refs_to_purge.append(parsed)

    await execute("DELETE FROM infra_certificates WHERE id = $1", cert_id)

    for vname, path in refs_to_purge:
        try:
            await vault_client.delete_secret(path, vault_name=vname)
        except Exception:
            _log.warning(
                "infra_certificates.vault_delete_failed",
                id=str(cert_id), vault=vname, path=path,
            )

    _log.info("infra_certificates.delete", id=str(cert_id))
