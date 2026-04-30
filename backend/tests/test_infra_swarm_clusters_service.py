"""Tests purs (pas de DB) pour les helpers chiffrement/decoding tokens."""
from __future__ import annotations

import os

# Fix la cle Fernet pour la reproductibilite (32 bytes url-safe base64)
os.environ["AGFLOW_INFRA_KEY"] = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="

from agflow.services.infra_swarm_clusters_service import (
    decrypt_tokens,
    encrypt_tokens,
)


def test_encrypt_tokens_returns_two_distinct_ciphertexts() -> None:
    enc = encrypt_tokens(worker="SWMTKN-1-worker-...", manager="SWMTKN-1-manager-...")
    assert "worker_encrypted" in enc
    assert "manager_encrypted" in enc
    assert enc["worker_encrypted"] != enc["manager_encrypted"]
    # Token clairs jamais retournes
    assert "SWMTKN-1-worker" not in str(enc)


def test_decrypt_tokens_round_trip() -> None:
    enc = encrypt_tokens(worker="WT-abc", manager="MT-xyz")
    dec = decrypt_tokens(
        worker_encrypted=enc["worker_encrypted"],
        manager_encrypted=enc["manager_encrypted"],
    )
    assert dec["worker"] == "WT-abc"
    assert dec["manager"] == "MT-xyz"
