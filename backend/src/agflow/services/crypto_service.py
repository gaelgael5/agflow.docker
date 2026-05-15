"""Fernet encryption service for infrastructure secrets.

Encrypts/decrypts passwords, private keys, and sensitive metadata at rest.
Key read from AGFLOW_INFRA_KEY environment variable.
"""
from __future__ import annotations

import re

import structlog
from cryptography.fernet import Fernet, InvalidToken

from agflow.utils.swarm_secrets import get_swarm_secret

_log = structlog.get_logger(__name__)

_SENSITIVE_PATTERNS = re.compile(
    r"(token|key|secret|password|kubeconfig|passphrase|credential)",
    re.IGNORECASE,
)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        raw = get_swarm_secret("agflow_infra_key", env_fallback="AGFLOW_INFRA_KEY")
        if raw:
            try:
                _fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
                return _fernet
            except ValueError:
                ephemeral = Fernet.generate_key()
                _log.error(
                    "crypto_service.invalid_key",
                    msg="AGFLOW_INFRA_KEY invalide (pas une clé Fernet 32 octets base64). "
                        "Utiliser une clé éphémère — les données chiffrées seront perdues au redémarrage. "
                        "Générez une clé valide avec : "
                        "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
                    suggested_key=ephemeral.decode(),
                )
                _fernet = Fernet(ephemeral)
        else:
            ephemeral = Fernet.generate_key()
            _log.warning(
                "crypto_service.no_key",
                msg="AGFLOW_INFRA_KEY non définie, clé éphémère utilisée — données perdues au redémarrage.",
                suggested_key=ephemeral.decode(),
            )
            _fernet = Fernet(ephemeral)
    return _fernet


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a Fernet-encrypted string."""
    if ciphertext is None:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        _log.error("crypto_service.decrypt_failed")
        return None


def is_sensitive_key(key: str) -> bool:
    """Check if a metadata key should be treated as sensitive."""
    return bool(_SENSITIVE_PATTERNS.search(key))
