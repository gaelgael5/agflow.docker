from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import bcrypt
import pytest
import pytest_asyncio
from asyncpg import Connection
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

from agflow.db.pool import get_pool  # noqa: E402
from agflow.main import create_app  # noqa: E402
from tests._db_reset import reset_schema_and_migrate  # noqa: E402
from tests._vault_mock import vault_mock  # noqa: E402, F401


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="session", autouse=True)
async def _close_pool_at_session_end():
    """Ferme le pool asyncpg une seule fois, en fin de session pytest.

    Auparavant, chaque fichier de test faisait `await close_pool()` dans son
    teardown function-scope. Combiné à `asyncio_default_test_loop_scope =
    "session"` et au lifespan FastAPI qui démarre des workers/pool, ça
    provoquait des `RuntimeError: Event loop is closed` en cascade dès qu'un
    fixture tentait de réutiliser le pool fermé.

    On centralise la fermeture ici : pool fermé une fois, à la fin de la
    session, après tous les tests. Entre tests, l'isolation DB se fait
    via `reset_schema_and_migrate()` (DROP+CREATE schéma public). Le pool
    reste ouvert et fonctionnel tout du long.
    """
    yield


# ── Fixtures DB partagées (services/ et api/) ──────────────────────


@pytest_asyncio.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture
async def mock_session_and_agent(fresh_db: Connection) -> tuple[UUID, UUID]:
    """Crée une api_key + session + agent_instance valides via INSERT direct."""
    # API key
    api_key_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO api_keys (id, name, prefix, key_hash, scopes)
        VALUES ($1, 'test', 'agfd_test', 'bcrypt-hash', '{m2m:orchestrate}')
        """,
        api_key_id,
    )
    # Agents catalog entry (FK)
    await fresh_db.execute(
        """
        INSERT INTO agents_catalog (slug)
        VALUES ('claude-r1')
        ON CONFLICT (slug) DO NOTHING
        """,
    )
    # Session
    session_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO sessions (id, api_key_id, expires_at)
        VALUES ($1, $2, now() + interval '1 hour')
        """,
        session_id,
        api_key_id,
    )
    # Agent instance
    agent_instance_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO agents_instances (id, session_id, agent_id, labels)
        VALUES ($1, $2, 'claude-r1', '{}'::jsonb)
        """,
        agent_instance_id,
        session_id,
    )
    return session_id, agent_instance_id

