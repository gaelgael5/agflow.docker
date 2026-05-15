from __future__ import annotations

import os
import tempfile

import bcrypt
import pytest
from fastapi.testclient import TestClient

# Compute a real bcrypt hash of "correct-password" for the test admin
_TEST_ADMIN_HASH = bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode()

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://agflow:agflow_dev@192.168.10.154:5432/agflow",
)
os.environ.setdefault("JWT_SECRET", "test-secret-key")
# `ADMIN_EMAIL` et `ADMIN_PASSWORD_HASH` sont FORCÉS (pas setdefault) :
# les tests envoient des credentials hardcodés (admin@example.com /
# correct-password), donc on doit s'assurer que le backend les attend,
# peu importe la valeur de .env dans le container. Sans cet override
# direct, le LXC de test garde son ADMIN_EMAIL=admin@<projet>.example.com
# et tous les tests qui passent par /api/admin/auth/login retournent 401.
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD_HASH"] = _TEST_ADMIN_HASH
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
# Isolated filesystem root for filesystem-backed services (agents, roles,
# templates, etc.). Wiped between tests via reset_schema_and_migrate.
os.environ.setdefault(
    "AGFLOW_DATA_DIR",
    os.path.join(tempfile.gettempdir(), "agflow_test_data"),
)

from agflow.main import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
