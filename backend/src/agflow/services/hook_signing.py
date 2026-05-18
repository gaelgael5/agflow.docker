"""Signature HMAC SHA-256 des hooks sortants workflow v5.

Conforme docs/contracts/hook-docker-task-completed.md §3.1 :

    signed_string = X-Agflow-Timestamp + "\\n" + X-Agflow-Hook-Id + "\\n" + raw_body
    signature_hex = HMAC_SHA256(secret, signed_string).hexdigest()
    header_value  = "hmac-sha256=" + signature_hex

Le secret arrive ici en clair hex (déchiffré par hmac_keys_service.get_by_key_id).

**Convention secret = `secret_hex.encode()` (UTF-8 du string hex)**, PAS
`bytes.fromhex(secret_hex)`. Cette convention est figée par le code de
référence côté ag.flow (mock receiver `docs/contracts/mock-docker/`,
3 fichiers cohérents). Toute modification doit être coordonnée avec ag.flow
pour préserver l'interopérabilité.
"""
from __future__ import annotations

import hashlib
import hmac


def sign(*, timestamp: str, hook_id: str, body: str, secret_hex: str) -> str:
    """Calcule la signature HMAC SHA-256 en hex (64 chars, sans préfixe).

    Le caller ajoute lui-même le préfixe 'hmac-sha256=' pour le header.
    """
    signed_string = f"{timestamp}\n{hook_id}\n{body}".encode()
    secret_bytes = secret_hex.encode()
    return hmac.new(secret_bytes, signed_string, hashlib.sha256).hexdigest()
