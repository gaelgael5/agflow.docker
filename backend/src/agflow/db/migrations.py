from __future__ import annotations

import hashlib
import re
from pathlib import Path

import asyncpg
import structlog

from agflow.db.pool import execute, get_pool

_log = structlog.get_logger(__name__)
_VERSION_RE = re.compile(r"^(\d{3,})_.*\.sql$")

# Cle int8 stable derivee d'un hash SHA-256 deterministe de l'identifiant
# "agflow_docker_migrations". Postgres advisory locks utilisent un int8 signe
# (range -2^63 .. 2^63 - 1) ; on tronque les 8 premiers octets du digest et on
# les interprete en signed big-endian.
#
# Pourquoi ce nom : il identifie de maniere unique la lock "migrations" de
# cette application dans l'espace global des advisory locks Postgres. Si une
# autre app partage la meme base, elle utilisera un autre nom -> pas de
# collision. La derivation est deterministe : la valeur ne change pas entre
# deux runs ni entre deux replicas, ce qui est essentiel pour que toutes les
# replicas tentent de prendre LA MEME lock.
_MIGRATIONS_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"agflow_docker_migrations").digest()[:8],
    byteorder="big",
    signed=True,
)


async def run_migrations(migrations_dir: Path) -> list[str]:
    """Apply all SQL files in `migrations_dir` that have not yet been applied.

    Returns the list of newly applied version strings (e.g. ['001_init']).

    Multi-replica safe : un advisory lock Postgres session-scoped serialise
    les migrations entre replicas. La premiere replica qui obtient le lock
    applique les migrations ; les autres attendent puis voient un
    schema_migrations deja a jour et n'appliquent rien.
    """
    await _ensure_bookkeeping_table()

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Tente le lock non-bloquant ; si une autre replica est en cours de
        # migration, on logue puis on attend en bloquant.
        got_lock = await conn.fetchval("SELECT pg_try_advisory_lock($1)", _MIGRATIONS_LOCK_KEY)
        if not got_lock:
            _log.info("migrations.waiting_for_lock", lock_key=_MIGRATIONS_LOCK_KEY)
            await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATIONS_LOCK_KEY)
            _log.info("migrations.lock_acquired", lock_key=_MIGRATIONS_LOCK_KEY)

        try:
            return await _apply_pending(conn, migrations_dir)
        finally:
            # Ceinture-bretelles : le lock est session-scoped donc Postgres le
            # libere automatiquement a la fermeture de connexion. On le release
            # explicitement quand meme pour ne pas le garder pendant toute la
            # duree de vie de la connexion poolee.
            await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATIONS_LOCK_KEY)


async def _apply_pending(conn: asyncpg.Connection, migrations_dir: Path) -> list[str]:
    """Apply pending migrations on the GIVEN connection.

    Reads schema_migrations on `conn`, applies each missing file in a
    transaction on `conn`, and returns the list of newly applied versions.

    Caller must hold the migrations advisory lock on `conn`.
    """
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    applied_versions = {r["version"] for r in rows}

    all_files = sorted(p for p in migrations_dir.glob("*.sql") if _VERSION_RE.match(p.name))

    newly_applied: list[str] = []
    for path in all_files:
        version = path.stem
        if version in applied_versions:
            continue
        sql = path.read_text(encoding="utf-8")
        _log.info("migrations.apply", version=version)
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations(version) VALUES ($1)", version)
        newly_applied.append(version)

    return newly_applied


async def _ensure_bookkeeping_table() -> None:
    await execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _cli() -> None:
    import asyncio

    from agflow.logging_setup import configure_logging

    configure_logging("INFO")
    migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
    applied = asyncio.run(run_migrations(migrations_dir))
    _log.info("migrations.done", applied=applied)


if __name__ == "__main__":
    _cli()
