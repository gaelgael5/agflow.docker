# Swarm Cluster + Infra Machines — Plan d'implémentation (Chantier B0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modéliser les clusters Swarm comme entité 1st-class dans M8 Infra, ingérer le JSON de création des LXC dans 8 colonnes typées sur `infra_machines`, et exposer 3 actions (`swarm_init`/`swarm_join`/`swarm_leave`) qui pilotent les scripts ops via SSH et persistent le résultat.

**Architecture:** Migration SQL 087 (nouvelle table `infra_swarm_clusters` + extension `infra_machines` + seed actions). Service helper `ingest_creation_output` qui mappe le JSON de `create-swarm-lxc.sh` aux colonnes typées. Service `infra_swarm_clusters_service` (CRUD + tokens Fernet). Service `swarm_actions_service` (3 actions orchestrées via `ssh_executor`). 4 endpoints API admin. Tests purs (mocking ssh_executor) + tests d'intégration.

**Tech Stack:** Python 3.12 + asyncpg + Pydantic v2 + Fernet (cryptography) + pytest + asyncssh (déjà en dep).

**Spec source:** `docs/superpowers/specs/2026-04-30-swarm-cluster-infra-design.md`

**Hors plan:** Frontend (page Swarm Clusters + enrichissement Machines) — plan séparé. Wiring automatique de `ingest_creation_output` dans le mécanisme `infra_named_type_actions` existant — chantier d'enhancement séparé.

---

## File Structure

| Fichier | Rôle | Action |
|---|---|---|
| `backend/migrations/087_swarm_clusters.sql` | Migration : nouvelle table + alter machines + seed actions | NOUVEAU |
| `backend/src/agflow/schemas/infra.py` | Pydantic schemas SwarmCluster + ingest_payload | MODIFIÉ (~80 lignes ajoutées en fin) |
| `backend/src/agflow/services/infra_machines_service.py` | Helper `ingest_creation_output` | MODIFIÉ (~80 lignes en fin) |
| `backend/src/agflow/services/infra_swarm_clusters_service.py` | CRUD clusters + tokens Fernet | NOUVEAU |
| `backend/src/agflow/services/swarm_actions_service.py` | `init_cluster`/`join_cluster`/`leave_cluster` orchestration | NOUVEAU |
| `backend/src/agflow/api/infra/swarm_clusters.py` | Router `/api/infra/swarm-clusters` (GET) | NOUVEAU |
| `backend/src/agflow/api/infra/machines.py` | Endpoints POST `/machines/{id}/actions/swarm_init|join|leave` + endpoint `ingest_creation_output` | MODIFIÉ |
| `backend/src/agflow/main.py` | Register `infra_swarm_clusters_router` | MODIFIÉ (1 ligne) |
| `backend/tests/test_infra_machines_ingest.py` | Tests `ingest_creation_output` | NOUVEAU |
| `backend/tests/test_infra_swarm_clusters_service.py` | Tests CRUD clusters + tokens | NOUVEAU |
| `backend/tests/test_swarm_actions_service.py` | Tests des 3 actions (mock ssh_executor) | NOUVEAU |
| `backend/tests/test_infra_swarm_clusters_endpoint.py` | Tests d'intégration HTTP | NOUVEAU |

---

## Task 1 — Migration 087 (DB schema)

**Files:**
- Create: `backend/migrations/087_swarm_clusters.sql`

- [ ] **Step 1 : Créer la migration**

Contenu exact :

```sql
-- 087_swarm_clusters.sql — Modélisation cluster Swarm + extension machines

-- ── Nouvelle table : cluster Swarm comme entité 1st-class ──────────────
CREATE TABLE IF NOT EXISTS infra_swarm_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL UNIQUE,
    manager_addr VARCHAR NOT NULL,
    join_token_worker_encrypted TEXT NOT NULL,
    join_token_manager_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_swarm_clusters_updated_at') THEN
        CREATE TRIGGER trg_infra_swarm_clusters_updated_at
            BEFORE UPDATE ON infra_swarm_clusters
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- ── Extension infra_machines : 8 colonnes 1st-class + 2 colonnes Swarm membership ──
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS ctid INTEGER;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS distro VARCHAR(64);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS ip_type VARCHAR(16);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS docker_version VARCHAR(32);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS compose_version VARCHAR(32);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_ready BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_mode VARCHAR(16);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS tun_device_present BOOLEAN;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_cluster_id UUID;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_node_role VARCHAR(16);

-- FK vers infra_swarm_clusters (idempotent)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'infra_machines_swarm_cluster_id_fkey'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT infra_machines_swarm_cluster_id_fkey
            FOREIGN KEY (swarm_cluster_id) REFERENCES infra_swarm_clusters(id) ON DELETE SET NULL;
    END IF;
END $$;

-- CHECK : role doit être manager|worker|NULL
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'swarm_node_role_chk'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT swarm_node_role_chk
            CHECK (swarm_node_role IN ('manager', 'worker') OR swarm_node_role IS NULL);
    END IF;
END $$;

-- CHECK : cohérence (cluster_id NULL ⇔ role NULL)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'swarm_membership_consistent_chk'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT swarm_membership_consistent_chk
            CHECK ((swarm_cluster_id IS NULL AND swarm_node_role IS NULL)
                OR (swarm_cluster_id IS NOT NULL AND swarm_node_role IS NOT NULL));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_infra_machines_swarm_cluster
    ON infra_machines (swarm_cluster_id) WHERE swarm_cluster_id IS NOT NULL;

-- ── Seed : 3 nouvelles category_actions sur catégorie 'service' ────────
INSERT INTO infra_category_actions (category, name, is_required) VALUES
    ('service', 'swarm_init',  FALSE),
    ('service', 'swarm_join',  FALSE),
    ('service', 'swarm_leave', FALSE)
ON CONFLICT (category, name) DO NOTHING;
```

- [ ] **Step 2 : Smoke test contre Postgres LXC 201**

Étape A — uploader 087 + 001_init sur le LXC :

```bash
scp backend/migrations/087_swarm_clusters.sql pve:/tmp/087.sql
scp backend/migrations/001_init.sql pve:/tmp/001_init.sql
ssh pve "pct push 201 /tmp/087.sql /tmp/087.sql && \
         pct push 201 /tmp/001_init.sql /tmp/001_init.sql && \
         pct exec 201 -- docker cp /tmp/001_init.sql agflow-postgres:/tmp/001_init.sql && \
         pct exec 201 -- docker cp /tmp/087.sql agflow-postgres:/tmp/087.sql"
```

Étape B — créer DB temp et appliquer les 2 migrations :

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -c 'DROP DATABASE IF EXISTS test_087'"
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -c 'CREATE DATABASE test_087'"
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d test_087 -v ON_ERROR_STOP=1 -f /tmp/001_init.sql 2>&1 | tail -3"
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d test_087 -v ON_ERROR_STOP=1 -f /tmp/087.sql 2>&1 | tail -3"
```

Étape C — vérifier table + seed actions :

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d test_087 -c '\\d infra_swarm_clusters'"
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d test_087 -tc \"SELECT name FROM infra_category_actions WHERE category = 'service' AND name LIKE 'swarm_%' ORDER BY name\""
```

Étape D — cleanup :

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -c 'DROP DATABASE test_087'"
```

Attendu :
- Étape B : migrations sans erreur, dernière ligne = `INSERT 0 3` ou similaire
- Étape C : `\d` affiche les 7 colonnes de `infra_swarm_clusters`, et 3 lignes pour les actions seedées (`swarm_init`, `swarm_join`, `swarm_leave`)

- [ ] **Step 3 : Test idempotence**

Re-applique `087.sql` sur la même DB temp → doit passer sans erreur (les `IF NOT EXISTS` + `DO $$` blocks rendent idempotent) :

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d test_087 -v ON_ERROR_STOP=1 -f /tmp/087.sql 2>&1"
```

- [ ] **Step 4 : Commit**

```bash
git add backend/migrations/087_swarm_clusters.sql
git commit -m "feat(db): migration 087 - infra_swarm_clusters + colonnes Swarm sur machines

- Nouvelle table infra_swarm_clusters (tokens chiffres Fernet, manager_addr, name)
- 8 colonnes 1st-class sur infra_machines : ctid, distro, ip_type,
  docker_version, compose_version, swarm_ready, swarm_mode, tun_device_present
- 2 colonnes Swarm membership : swarm_cluster_id (FK), swarm_node_role
- 2 CHECK constraints : role IN (manager|worker|NULL) + coherence cluster<->role
- 3 actions seed : swarm_init, swarm_join, swarm_leave (categorie service)

Idempotente : IF NOT EXISTS partout. Smoke teste sur DB temp Postgres 16."
```

---

## Task 2 — Pydantic schemas SwarmCluster + ingest

**Files:**
- Modify: `backend/src/agflow/schemas/infra.py` (ajout en fin)

- [ ] **Step 1 : Schemas pour les API/services**

Ajouter à la fin de `backend/src/agflow/schemas/infra.py` :

```python
# ── Swarm clusters (B0) ──────────────────────────────────────────────────


class SwarmClusterRow(BaseModel):
    """Public representation of a Swarm cluster. Tokens NEVER exposed."""

    id: UUID
    name: str
    manager_addr: str
    node_count: int = 0
    manager_count: int = 0
    worker_count: int = 0
    created_at: datetime
    updated_at: datetime


class SwarmInitRequest(BaseModel):
    cluster_name: str = Field(..., min_length=1, max_length=64)


class SwarmJoinRequest(BaseModel):
    cluster_id: UUID
    role: str = Field(..., pattern="^(manager|worker)$")


class SwarmLeaveRequest(BaseModel):
    force: bool = False


# ── Ingestion JSON depuis create-swarm-lxc.sh ────────────────────────────


class _Identification(BaseModel):
    ctid: int
    hostname: str
    hostname_raw: str | None = None


class _Systeme(BaseModel):
    distro: str
    ip: str
    ip_type: str = Field(..., pattern="^(static|dhcp)$")


class _UserBlock(BaseModel):
    user: str
    password: str | None = None
    ssh_key_private_path: str | None = None
    ssh_key_public_path: str | None = None
    ssh_key_public: str | None = None
    groups: list[str] = []
    sudo_nopasswd: bool = False


class _DockerBlock(BaseModel):
    docker_ok: bool
    docker_version: str | None = None
    compose_version: str | None = None
    hello_world_ok: bool | None = None


class _SwarmBlock(BaseModel):
    swarm_mode: str
    swarm_ready: bool
    tun_device_present: bool | None = None


class _HostBlock(BaseModel):
    proxmox_host: str | None = None
    created_at: str | None = None
    script_version: str | None = None
    conf_path: str | None = None
    conf_backup_path: str | None = None


class CreateLxcOutput(BaseModel):
    """JSON contract returned by create-swarm-lxc.sh (Configurations repo)."""

    status: str = Field(..., pattern="^(ok|partial)$")
    exit_code: int
    identification: _Identification
    ressources: dict | None = None
    systeme: _Systeme
    ssh_root: dict | None = None
    users: list[_UserBlock]
    docker: _DockerBlock
    swarm: _SwarmBlock
    host: _HostBlock | None = None
```

- [ ] **Step 2 : Smoke import check**

```bash
cd backend && uv run python -c "
from agflow.schemas.infra import (
    SwarmClusterRow, SwarmInitRequest, SwarmJoinRequest, SwarmLeaveRequest,
    CreateLxcOutput,
)
print('ok')
"
```

Attendu : `ok`.

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check src/agflow/schemas/infra.py
```

Attendu : clean.

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/schemas/infra.py
git commit -m "feat(schemas): SwarmCluster* et CreateLxcOutput pour B0

- SwarmClusterRow (public, tokens jamais exposés)
- SwarmInitRequest / SwarmJoinRequest / SwarmLeaveRequest
- CreateLxcOutput : contrat JSON du script create-swarm-lxc.sh"
```

---

## Task 3 — `ingest_creation_output` helper dans `infra_machines_service`

**Files:**
- Modify: `backend/src/agflow/services/infra_machines_service.py` (ajout en fin)
- Create: `backend/tests/test_infra_machines_ingest.py`

- [ ] **Step 1 : Tests rouges**

Créer `backend/tests/test_infra_machines_ingest.py` :

```python
"""Tests purs (pas de DB) pour ingest_creation_output : extraction des champs
1st-class depuis le JSON CreateLxcOutput vers le mapping DB."""
from __future__ import annotations

from agflow.schemas.infra import CreateLxcOutput
from agflow.services.infra_machines_service import (
    derive_machine_columns_from_output,
    derive_metadata_from_output,
)


_SAMPLE_JSON = {
    "status": "ok",
    "exit_code": 0,
    "identification": {"ctid": 300, "hostname": "swarm1-mgr", "hostname_raw": "swarm1-mgr"},
    "ressources": {"storage": "20G"},
    "systeme": {"distro": "debian-12", "ip": "192.168.10.300", "ip_type": "static"},
    "ssh_root": {"login_method": "key-only"},
    "users": [
        {"user": "agflow", "groups": ["sudo", "docker"], "sudo_nopasswd": True,
         "ssh_key_public": "ssh-ed25519 AAA..."},
    ],
    "docker": {"docker_ok": True, "docker_version": "29.4", "compose_version": "5.1",
               "hello_world_ok": True},
    "swarm": {"swarm_mode": "inactive", "swarm_ready": True, "tun_device_present": True},
    "host": {"proxmox_host": "pve", "script_version": "1.0",
             "conf_path": "/etc/pve/lxc/300.conf"},
}


def test_derive_machine_columns_extracts_1st_class_fields() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    cols = derive_machine_columns_from_output(out)

    assert cols["name"] == "swarm1-mgr"
    assert cols["host"] == "192.168.10.300"
    assert cols["username"] == "agflow"
    assert cols["ctid"] == 300
    assert cols["distro"] == "debian-12"
    assert cols["ip_type"] == "static"
    assert cols["docker_version"] == "29.4"
    assert cols["compose_version"] == "5.1"
    assert cols["swarm_ready"] is True
    assert cols["swarm_mode"] == "inactive"
    assert cols["tun_device_present"] is True


def test_derive_machine_columns_status_ready_when_docker_ok_and_static_ip() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    cols = derive_machine_columns_from_output(out)
    assert cols["status"] == "ready"


def test_derive_machine_columns_status_partial_when_docker_not_ok() -> None:
    payload = {**_SAMPLE_JSON, "docker": {**_SAMPLE_JSON["docker"], "docker_ok": False}}
    out = CreateLxcOutput.model_validate(payload)
    cols = derive_machine_columns_from_output(out)
    assert cols["status"] == "partial"


def test_derive_metadata_includes_residual_fields() -> None:
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    meta = derive_metadata_from_output(out)

    # Champs résiduels qui DOIVENT etre dans metadata
    assert meta["storage"] == "20G"
    assert meta["script_version"] == "1.0"
    assert meta["conf_path"] == "/etc/pve/lxc/300.conf"
    assert meta["agflow_user_groups"] == ["sudo", "docker"]
    assert meta["agflow_sudo_nopasswd"] is True
    assert meta["docker_hello_world_ok"] is True


def test_derive_metadata_does_not_include_1st_class_fields() -> None:
    """Defense contre la duplication : ce qui est en colonne ne doit pas etre en JSONB."""
    out = CreateLxcOutput.model_validate(_SAMPLE_JSON)
    meta = derive_metadata_from_output(out)

    # Aucun de ces fields ne doit etre dans metadata (ils sont en colonnes 1st-class)
    for forbidden in ["ctid", "hostname", "ip", "ip_type", "distro",
                      "docker_version", "compose_version", "swarm_ready",
                      "swarm_mode", "tun_device_present"]:
        assert forbidden not in meta, f"{forbidden} doit etre en colonne, pas en metadata"
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_infra_machines_ingest.py -v
```

Attendu : `ImportError` sur les 2 fonctions.

- [ ] **Step 3 : Implémentation**

Ajouter à la fin de `backend/src/agflow/services/infra_machines_service.py` :

```python
# ── B0 : ingestion JSON create-swarm-lxc → colonnes 1st-class + metadata ──


def derive_machine_columns_from_output(output: "CreateLxcOutput") -> dict[str, Any]:  # noqa: F821
    """Map le JSON CreateLxcOutput vers les colonnes typees de infra_machines.

    Ne retourne que les colonnes 1st-class (sans metadata). Le statut est
    derive : 'ready' si docker.docker_ok et systeme.ip_type valide, sinon
    'partial'. Les imports sont locaux pour eviter un import circulaire avec
    schemas.infra.
    """
    agflow_user = output.users[0] if output.users else None
    docker_ok = output.docker.docker_ok
    ip_type_valid = output.systeme.ip_type in ("static", "dhcp")
    return {
        "name": output.identification.hostname,
        "host": output.systeme.ip,
        "username": agflow_user.user if agflow_user else None,
        "ctid": output.identification.ctid,
        "distro": output.systeme.distro,
        "ip_type": output.systeme.ip_type,
        "docker_version": output.docker.docker_version,
        "compose_version": output.docker.compose_version,
        "swarm_ready": output.swarm.swarm_ready,
        "swarm_mode": output.swarm.swarm_mode,
        "tun_device_present": output.swarm.tun_device_present,
        "status": "ready" if (docker_ok and ip_type_valid) else "partial",
    }


def derive_metadata_from_output(output: "CreateLxcOutput") -> dict[str, Any]:  # noqa: F821
    """Champs residuels du JSON qui ne sont PAS en colonnes 1st-class.

    Utilise pour peupler infra_machines.metadata (JSONB). Inclut le user
    agflow secondary metadata, les paths de conf, le hello_world_ok docker.
    """
    meta: dict[str, Any] = {}
    if output.ressources and "storage" in output.ressources:
        meta["storage"] = output.ressources["storage"]
    if output.host:
        if output.host.script_version is not None:
            meta["script_version"] = output.host.script_version
        if output.host.conf_path is not None:
            meta["conf_path"] = output.host.conf_path
        if output.host.conf_backup_path is not None:
            meta["conf_backup_path"] = output.host.conf_backup_path
    if output.users:
        agflow_user = output.users[0]
        meta["agflow_user_groups"] = list(agflow_user.groups)
        meta["agflow_sudo_nopasswd"] = agflow_user.sudo_nopasswd
    if output.docker.hello_world_ok is not None:
        meta["docker_hello_world_ok"] = output.docker.hello_world_ok
    return meta
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_infra_machines_ingest.py -v
```

Attendu : 5 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/infra_machines_service.py tests/test_infra_machines_ingest.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/infra_machines_service.py backend/tests/test_infra_machines_ingest.py
git commit -m "feat(infra-machines): helper ingest_creation_output (mapping JSON -> colonnes 1st-class)

Pure functions : derive_machine_columns_from_output + derive_metadata_from_output.
Le statut 'ready' est derive de docker.docker_ok && ip_type valide. 5 tests
unitaires couvrent les 2 helpers + le defense contre duplication colonne/JSONB."
```

---

## Task 4 — Service `infra_swarm_clusters_service` (CRUD + tokens Fernet)

**Files:**
- Create: `backend/src/agflow/services/infra_swarm_clusters_service.py`
- Create: `backend/tests/test_infra_swarm_clusters_service.py`

- [ ] **Step 1 : Tests rouges (helpers purs sans DB)**

Créer `backend/tests/test_infra_swarm_clusters_service.py` :

```python
"""Tests purs (pas de DB) pour les helpers chiffrement/decoding tokens."""
from __future__ import annotations

import os

# Fix la cle Fernet pour la reproductibilite
os.environ["AGFLOW_INFRA_KEY"] = "32-byte-key-base64-padded-AAAAAAAAAAAAAA="

from agflow.services.infra_swarm_clusters_service import (
    encrypt_tokens,
    decrypt_tokens,
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
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_infra_swarm_clusters_service.py -v
```

Attendu : `ImportError`.

- [ ] **Step 3 : Implémentation du service**

Créer `backend/src/agflow/services/infra_swarm_clusters_service.py` :

```python
"""Infra swarm clusters service — CRUD + tokens Fernet.

Tokens Worker/Manager sont chiffres au repos via crypto_service (Fernet).
Decrypt uniquement en memoire au moment d'un swarm_join.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services import crypto_service

_log = structlog.get_logger(__name__)

_LIST_SQL = """
    SELECT
        c.id, c.name, c.manager_addr, c.created_at, c.updated_at,
        COUNT(m.id) FILTER (WHERE m.swarm_cluster_id IS NOT NULL) AS node_count,
        COUNT(m.id) FILTER (WHERE m.swarm_node_role = 'manager')  AS manager_count,
        COUNT(m.id) FILTER (WHERE m.swarm_node_role = 'worker')   AS worker_count
    FROM infra_swarm_clusters c
    LEFT JOIN infra_machines m ON m.swarm_cluster_id = c.id
    GROUP BY c.id
    ORDER BY c.name
"""


# ── Tokens helpers (purs, testables sans DB) ─────────────────────────────


def encrypt_tokens(*, worker: str, manager: str) -> dict[str, str]:
    """Encrypt worker + manager tokens via Fernet. Returns dict with the 2 ciphertexts."""
    return {
        "worker_encrypted": crypto_service.encrypt(worker) or "",
        "manager_encrypted": crypto_service.encrypt(manager) or "",
    }


def decrypt_tokens(*, worker_encrypted: str, manager_encrypted: str) -> dict[str, str]:
    """Decrypt tokens. Returns clear-text tokens. NEVER persist or log results."""
    return {
        "worker": crypto_service.decrypt(worker_encrypted) or "",
        "manager": crypto_service.decrypt(manager_encrypted) or "",
    }


# ── CRUD (DB-bound, integration tested via endpoints) ────────────────────


async def list_all() -> list[dict[str, Any]]:
    """List all clusters with node counts. Tokens NEVER returned."""
    rows = await fetch_all(_LIST_SQL)
    return [dict(r) for r in rows]


async def get_by_id(cluster_id: UUID) -> dict[str, Any] | None:
    """Get one cluster by id. Tokens NEVER returned."""
    row = await fetch_one(
        _LIST_SQL.replace("ORDER BY c.name", "HAVING c.id = $1 ORDER BY c.name"),
        cluster_id,
    )
    return dict(row) if row else None


async def get_with_tokens(cluster_id: UUID) -> dict[str, Any] | None:
    """Internal-only : returns cluster row + ENCRYPTED tokens.

    Used by swarm_join orchestration. Caller is responsible for decryption
    via decrypt_tokens() and must NOT persist or log the clear values.
    """
    return await fetch_one(
        """
        SELECT id, name, manager_addr,
               join_token_worker_encrypted, join_token_manager_encrypted,
               created_at, updated_at
        FROM infra_swarm_clusters WHERE id = $1
        """,
        cluster_id,
    )


async def create(
    *,
    name: str,
    manager_addr: str,
    join_token_worker: str,
    join_token_manager: str,
) -> dict[str, Any]:
    """Create a cluster. Tokens are encrypted Fernet before storage."""
    enc = encrypt_tokens(worker=join_token_worker, manager=join_token_manager)
    row = await fetch_one(
        """
        INSERT INTO infra_swarm_clusters
            (name, manager_addr, join_token_worker_encrypted, join_token_manager_encrypted)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, manager_addr, created_at, updated_at
        """,
        name, manager_addr, enc["worker_encrypted"], enc["manager_encrypted"],
    )
    _log.info("swarm_cluster.created", cluster_id=str(row["id"]) if row else None, name=name)
    assert row is not None  # RETURNING garanti
    return dict(row)


async def delete(cluster_id: UUID) -> None:
    """Delete a cluster. FK ON DELETE SET NULL on infra_machines."""
    await execute("DELETE FROM infra_swarm_clusters WHERE id = $1", cluster_id)
    _log.info("swarm_cluster.deleted", cluster_id=str(cluster_id))


async def is_last_node(cluster_id: UUID, exclude_machine_id: UUID) -> bool:
    """Returns True if `cluster_id` has 0 nodes besides `exclude_machine_id`."""
    row = await fetch_one(
        """
        SELECT COUNT(*) AS cnt FROM infra_machines
        WHERE swarm_cluster_id = $1 AND id != $2
        """,
        cluster_id, exclude_machine_id,
    )
    return (row["cnt"] if row else 0) == 0
```

- [ ] **Step 4 : Run, vérifier que les tests purs passent**

```bash
cd backend && uv run pytest tests/test_infra_swarm_clusters_service.py -v
```

Attendu : 2 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/infra_swarm_clusters_service.py tests/test_infra_swarm_clusters_service.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/infra_swarm_clusters_service.py backend/tests/test_infra_swarm_clusters_service.py
git commit -m "feat(infra-swarm-clusters): service CRUD + tokens Fernet

- encrypt_tokens / decrypt_tokens helpers (testes purs)
- list_all / get_by_id : retournent counts mais JAMAIS les tokens
- get_with_tokens : usage interne pour swarm_join, retourne tokens chiffres
- create / delete / is_last_node : utilities CRUD
2 tests unitaires sur les helpers Fernet."
```

---

## Task 5 — Service `swarm_actions_service.init_cluster`

**Files:**
- Create: `backend/src/agflow/services/swarm_actions_service.py`
- Create: `backend/tests/test_swarm_actions_service.py`

- [ ] **Step 1 : Tests rouges**

Créer `backend/tests/test_swarm_actions_service.py` :

```python
"""Tests pour swarm_actions_service avec mocks ssh_executor + DB layer."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ["AGFLOW_INFRA_KEY"] = "32-byte-key-base64-padded-AAAAAAAAAAAAAA="

import pytest

from agflow.services.swarm_actions_service import (
    SwarmActionError,
    init_cluster,
)


_INIT_SCRIPT_OUTPUT = {
    "status": "ok",
    "exit_code": 0,
    "swarm": {
        "cluster_name": "swarm1",
        "manager_addr": "192.168.10.300:2377",
        "join_token_worker": "SWMTKN-1-worker-abc",
        "join_token_manager": "SWMTKN-1-manager-xyz",
    },
}


@pytest.mark.asyncio
async def test_init_cluster_runs_script_and_persists() -> None:
    machine_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "192.168.10.300", "port": 22,
            "username": "agflow", "swarm_ready": True, "swarm_cluster_id": None,
            "certificate_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value=_INIT_SCRIPT_OUTPUT)) as mock_exec,
        patch("agflow.services.swarm_actions_service._persist_init_result",
              AsyncMock(return_value={"id": uuid4(), "name": "swarm1"})) as mock_persist,
    ):
        result = await init_cluster(machine_id=machine_id, cluster_name="swarm1")

    assert mock_exec.called
    assert mock_persist.called
    assert result["name"] == "swarm1"


@pytest.mark.asyncio
async def test_init_cluster_rejects_machine_already_in_cluster() -> None:
    machine_id = uuid4()

    with patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
        "id": machine_id, "swarm_cluster_id": uuid4(),  # already member
    })):
        with pytest.raises(SwarmActionError, match="already member"):
            await init_cluster(machine_id=machine_id, cluster_name="swarm2")


@pytest.mark.asyncio
async def test_init_cluster_rejects_machine_not_swarm_ready() -> None:
    machine_id = uuid4()

    with patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
        "id": machine_id, "swarm_ready": False, "swarm_cluster_id": None,
    })):
        with pytest.raises(SwarmActionError, match="not swarm-ready"):
            await init_cluster(machine_id=machine_id, cluster_name="swarm1")


@pytest.mark.asyncio
async def test_init_cluster_rejects_when_script_returns_partial() -> None:
    machine_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "swarm_ready": True, "swarm_cluster_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "partial", "exit_code": 2})),
    ):
        with pytest.raises(SwarmActionError, match="partial"):
            await init_cluster(machine_id=machine_id, cluster_name="swarm1")
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_swarm_actions_service.py -v
```

Attendu : `ImportError`.

- [ ] **Step 3 : Implémentation `init_cluster` + helpers privés**

Créer `backend/src/agflow/services/swarm_actions_service.py` :

```python
"""Swarm actions service : init/join/leave orchestration.

Chaque action :
  1. Charge la machine cible (DB)
  2. Verifie les preconditions (swarm_ready, membership exclusivite)
  3. Lance le script ops via ssh_executor
  4. Parse le JSON de retour
  5. Persiste en DB (swarm_clusters + machines)
  6. Trace dans infra_machines_runs

Si l'une des etapes echoue, leve SwarmActionError (capture par le router HTTP).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_one
from agflow.services import (
    infra_certificates_service,
    infra_swarm_clusters_service,
    ssh_executor,
)

_log = structlog.get_logger(__name__)


class SwarmActionError(Exception):
    """Raised when a swarm_init/join/leave action fails on preconditions or script."""


# ── Helpers prives (overridable via patch dans les tests) ────────────────


async def _get_machine(machine_id: UUID) -> dict[str, Any] | None:
    return await fetch_one(
        """
        SELECT id, host, port, username, certificate_id, swarm_ready,
               swarm_mode, swarm_cluster_id, swarm_node_role
        FROM infra_machines WHERE id = $1
        """,
        machine_id,
    )


async def _exec_swarm_script(
    machine: dict[str, Any], script_args: list[str]
) -> dict[str, Any]:
    """Run init-swarm-node.sh via ssh on the target machine, parse JSON output."""
    private_key = None
    passphrase = None
    if machine.get("certificate_id"):
        cert = await infra_certificates_service.get(machine["certificate_id"])
        if cert:
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

    cmd = "init-swarm-node.sh " + " ".join(script_args)
    result = await ssh_executor.exec_command(
        host=machine["host"],
        port=machine["port"],
        username=machine["username"],
        password=None,
        private_key=private_key,
        passphrase=passphrase,
        command=cmd,
    )
    if result["exit_code"] != 0:
        raise SwarmActionError(
            f"Script failed (exit_code={result['exit_code']}): {result['stderr'][:200]}"
        )
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise SwarmActionError(f"Script output is not valid JSON: {exc}") from exc


async def _persist_init_result(
    *, machine_id: UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    """Insert cluster + link machine. Returns the created cluster row (no tokens)."""
    swarm_block = payload["swarm"]
    cluster = await infra_swarm_clusters_service.create(
        name=swarm_block["cluster_name"],
        manager_addr=swarm_block["manager_addr"],
        join_token_worker=swarm_block["join_token_worker"],
        join_token_manager=swarm_block["join_token_manager"],
    )
    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = $1,
            swarm_node_role = 'manager',
            swarm_mode = 'active'
        WHERE id = $2
        """,
        cluster["id"], machine_id,
    )
    return cluster


# ── Public API ───────────────────────────────────────────────────────────


async def init_cluster(*, machine_id: UUID, cluster_name: str) -> dict[str, Any]:
    """Initialise un nouveau cluster Swarm sur la machine cible.

    Preconditions :
    - machine.swarm_ready = TRUE
    - machine.swarm_cluster_id IS NULL (pas deja membre)

    Levée SwarmActionError sur violation de precondition ou echec script.
    Retourne le row du cluster cree (sans tokens).
    """
    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if not machine.get("swarm_ready"):
        raise SwarmActionError(f"Machine {machine_id} is not swarm-ready")
    if machine.get("swarm_cluster_id") is not None:
        raise SwarmActionError(f"Machine {machine_id} is already member of a cluster")

    payload = await _exec_swarm_script(machine, ["--init", "--name", cluster_name])
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    cluster = await _persist_init_result(machine_id=machine_id, payload=payload)
    _log.info("swarm.init", machine_id=str(machine_id), cluster_id=str(cluster["id"]))
    return cluster
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_swarm_actions_service.py -v
```

Attendu : 4 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/swarm_actions_service.py tests/test_swarm_actions_service.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/swarm_actions_service.py backend/tests/test_swarm_actions_service.py
git commit -m "feat(swarm-actions): init_cluster (run script + persist cluster + link machine)

Preconditions verifiees : machine.swarm_ready et pas deja membre. Script ops
init-swarm-node.sh --init lance via ssh_executor, JSON parse. Cluster cree
avec tokens chiffres Fernet, machine liee en role=manager + swarm_mode=active.
4 tests unitaires (mocks complete chaine SSH + DB)."
```

---

## Task 6 — `swarm_actions_service.join_cluster` + `leave_cluster`

**Files:**
- Modify: `backend/src/agflow/services/swarm_actions_service.py` (ajout 2 fonctions)
- Modify: `backend/tests/test_swarm_actions_service.py` (ajout tests)

- [ ] **Step 1 : Tests rouges**

Ajouter à `backend/tests/test_swarm_actions_service.py` (en bas) :

```python
from agflow.services.swarm_actions_service import join_cluster, leave_cluster


@pytest.mark.asyncio
async def test_join_cluster_succeeds_with_worker_role() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "192.168.10.301", "port": 22,
            "username": "agflow", "swarm_ready": True, "swarm_cluster_id": None,
            "certificate_id": None,
        })),
        patch(
            "agflow.services.infra_swarm_clusters_service.get_with_tokens",
            AsyncMock(return_value={
                "id": cluster_id, "name": "swarm1", "manager_addr": "10.0.0.1:2377",
                "join_token_worker_encrypted": "ENC1",
                "join_token_manager_encrypted": "ENC2",
            }),
        ),
        patch(
            "agflow.services.infra_swarm_clusters_service.decrypt_tokens",
            return_value={"worker": "WT-clear", "manager": "MT-clear"},
        ),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0,
                                       "swarm": {"joined": True, "node_id": "n1", "role": "worker"}})),
    ):
        result = await join_cluster(machine_id=machine_id, cluster_id=cluster_id, role="worker")

    assert result["joined"] is True
    assert result["role"] == "worker"


@pytest.mark.asyncio
async def test_join_cluster_rejects_unknown_cluster() -> None:
    machine_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "swarm_ready": True, "swarm_cluster_id": None,
        })),
        patch(
            "agflow.services.infra_swarm_clusters_service.get_with_tokens",
            AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(SwarmActionError, match="Cluster .* not found"):
            await join_cluster(machine_id=machine_id, cluster_id=uuid4(), role="worker")


@pytest.mark.asyncio
async def test_leave_cluster_drops_cluster_when_last_node() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "10.0.0.2", "port": 22, "username": "agflow",
            "swarm_cluster_id": cluster_id, "swarm_node_role": "manager",
            "certificate_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0, "swarm": {"left": True}})),
        patch("agflow.services.infra_swarm_clusters_service.is_last_node",
              AsyncMock(return_value=True)),
        patch("agflow.services.infra_swarm_clusters_service.delete",
              AsyncMock()) as mock_delete,
    ):
        result = await leave_cluster(machine_id=machine_id)

    assert result["left"] is True
    assert result["cluster_dropped"] is True
    mock_delete.assert_called_once_with(cluster_id)


@pytest.mark.asyncio
async def test_leave_cluster_keeps_cluster_when_other_nodes_remain() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "10.0.0.3", "port": 22, "username": "agflow",
            "swarm_cluster_id": cluster_id, "swarm_node_role": "worker",
            "certificate_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0, "swarm": {"left": True}})),
        patch("agflow.services.infra_swarm_clusters_service.is_last_node",
              AsyncMock(return_value=False)),
        patch("agflow.services.infra_swarm_clusters_service.delete",
              AsyncMock()) as mock_delete,
    ):
        result = await leave_cluster(machine_id=machine_id)

    assert result["left"] is True
    assert result["cluster_dropped"] is False
    mock_delete.assert_not_called()
```

- [ ] **Step 2 : Run, vérifier les rouges**

```bash
cd backend && uv run pytest tests/test_swarm_actions_service.py -v
```

Attendu : 4 verts (Task 5) + 4 rouges (`ImportError` sur `join_cluster` / `leave_cluster`).

- [ ] **Step 3 : Implémentation des 2 fonctions**

Ajouter à la fin de `backend/src/agflow/services/swarm_actions_service.py` :

```python
async def join_cluster(
    *, machine_id: UUID, cluster_id: UUID, role: str
) -> dict[str, Any]:
    """Joint la machine au cluster existant en role 'manager' ou 'worker'.

    Preconditions : machine.swarm_ready, pas deja membre, cluster existe.
    Token deciphere uniquement en memoire pour le passer au script ops.
    """
    if role not in ("manager", "worker"):
        raise SwarmActionError(f"Invalid role '{role}' (expected manager|worker)")

    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if not machine.get("swarm_ready"):
        raise SwarmActionError(f"Machine {machine_id} is not swarm-ready")
    if machine.get("swarm_cluster_id") is not None:
        raise SwarmActionError(f"Machine {machine_id} is already member of a cluster")

    cluster = await infra_swarm_clusters_service.get_with_tokens(cluster_id)
    if cluster is None:
        raise SwarmActionError(f"Cluster {cluster_id} not found")

    tokens = infra_swarm_clusters_service.decrypt_tokens(
        worker_encrypted=cluster["join_token_worker_encrypted"],
        manager_encrypted=cluster["join_token_manager_encrypted"],
    )
    token = tokens["manager"] if role == "manager" else tokens["worker"]

    args = ["--join", "--manager", str(cluster["manager_addr"]), "--token", token]
    if role == "manager":
        args.append("--manager-role")
    payload = await _exec_swarm_script(machine, args)
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = $1,
            swarm_node_role = $2,
            swarm_mode = 'active'
        WHERE id = $3
        """,
        cluster_id, role, machine_id,
    )
    _log.info("swarm.join", machine_id=str(machine_id), cluster_id=str(cluster_id), role=role)
    return {
        "joined": payload["swarm"].get("joined", True),
        "node_id": payload["swarm"].get("node_id"),
        "role": role,
    }


async def leave_cluster(*, machine_id: UUID, force: bool = False) -> dict[str, Any]:
    """Retire la machine de son cluster. Drop le cluster si dernier node."""
    machine = await _get_machine(machine_id)
    if machine is None:
        raise SwarmActionError(f"Machine {machine_id} not found")
    if machine.get("swarm_cluster_id") is None:
        raise SwarmActionError(f"Machine {machine_id} is not part of any cluster")

    cluster_id_was = machine["swarm_cluster_id"]

    args = ["--leave"] + (["--force"] if force else [])
    payload = await _exec_swarm_script(machine, args)
    if payload.get("status") != "ok":
        raise SwarmActionError(
            f"Script returned partial status (exit_code={payload.get('exit_code')})"
        )

    await execute(
        """
        UPDATE infra_machines SET
            swarm_cluster_id = NULL,
            swarm_node_role = NULL,
            swarm_mode = 'inactive'
        WHERE id = $1
        """,
        machine_id,
    )

    cluster_dropped = False
    if await infra_swarm_clusters_service.is_last_node(cluster_id_was, machine_id):
        await infra_swarm_clusters_service.delete(cluster_id_was)
        cluster_dropped = True

    _log.info("swarm.leave", machine_id=str(machine_id), cluster_dropped=cluster_dropped)
    return {"left": True, "cluster_dropped": cluster_dropped}
```

- [ ] **Step 4 : Run, vérifier que tout passe**

```bash
cd backend && uv run pytest tests/test_swarm_actions_service.py -v
```

Attendu : 8 verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/swarm_actions_service.py tests/test_swarm_actions_service.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/swarm_actions_service.py backend/tests/test_swarm_actions_service.py
git commit -m "feat(swarm-actions): join_cluster + leave_cluster

- join_cluster : decrypt token in memory only, call script with --join,
  link machine to existing cluster (role manager|worker)
- leave_cluster : call script --leave, unlink machine, DROP cluster if
  this was the last node (is_last_node check)
4 nouveaux tests unitaires (8 total)."
```

---

## Task 7 — Router GET `/api/infra/swarm-clusters`

**Files:**
- Create: `backend/src/agflow/api/infra/swarm_clusters.py`
- Modify: `backend/src/agflow/main.py` (1 ligne import + 1 ligne register)

- [ ] **Step 1 : Créer le router**

Créer `backend/src/agflow/api/infra/swarm_clusters.py` :

```python
"""GET endpoints for Swarm clusters (read-only)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.services import infra_swarm_clusters_service

router = APIRouter(
    prefix="/api/infra/swarm-clusters",
    tags=["infra-swarm-clusters"],
    dependencies=[Depends(require_admin)],
)


@router.get("", summary="List all Swarm clusters")
async def list_clusters() -> list[dict[str, Any]]:
    """Liste tous les clusters Swarm avec leur compte de nodes (manager/worker).

    Tokens JAMAIS retournes en clair.
    """
    return await infra_swarm_clusters_service.list_all()


@router.get("/{cluster_id}", summary="Get a Swarm cluster by id")
async def get_cluster(cluster_id: UUID) -> dict[str, Any]:
    cluster = await infra_swarm_clusters_service.get_by_id(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    return cluster
```

- [ ] **Step 2 : Enregistrer le router dans main.py**

Dans `backend/src/agflow/main.py`, après la ligne `from agflow.api.infra.named_types import router as infra_named_types_router` (autour ligne 47), ajouter :

```python
from agflow.api.infra.swarm_clusters import router as infra_swarm_clusters_router
```

Et après `app.include_router(infra_machines_router)` (autour ligne 316), ajouter :

```python
    app.include_router(infra_swarm_clusters_router)
```

- [ ] **Step 3 : Smoke import**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('boot ok')"
```

Attendu : `boot ok`.

- [ ] **Step 4 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/infra/swarm_clusters.py src/agflow/main.py
```

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/api/infra/swarm_clusters.py backend/src/agflow/main.py
git commit -m "feat(api): GET /api/infra/swarm-clusters (list + detail)

Tokens jamais retournes en clair par l'API. Auth require_admin (alias
require_operator existant). Enregistrement dans main.py."
```

---

## Task 8 — Endpoints actions `swarm_init`/`swarm_join`/`swarm_leave` sur `/machines/{id}`

**Files:**
- Modify: `backend/src/agflow/api/infra/machines.py` (ajout endpoints en fin)

- [ ] **Step 1 : Ajouter les imports nécessaires**

En haut de `backend/src/agflow/api/infra/machines.py`, dans le bloc `from agflow.schemas.infra import (...)`, ajouter :

```python
from agflow.schemas.infra import (
    MachineCreate,
    MachineSummary,
    MachineUpdate,
    ScriptRunRequest,
    SwarmInitRequest,                     # ← AJOUT
    SwarmJoinRequest,                     # ← AJOUT
    SwarmLeaveRequest,                    # ← AJOUT
)
```

Dans le bloc `from agflow.services import (...)`, ajouter :

```python
from agflow.services import (
    infra_certificates_service,
    infra_machines_runs_service,
    infra_machines_service,
    infra_named_type_actions_service,
    infra_named_types_service,
    ssh_executor,
    swarm_actions_service,                # ← AJOUT
)
```

- [ ] **Step 2 : Ajouter les 3 endpoints à la fin du fichier `machines.py`**

```python
# ── B0 : Swarm actions ─────────────────────────────────────────────────


@router.post(
    "/{machine_id}/actions/swarm_init",
    summary="Initialize a new Swarm cluster on this machine",
)
async def action_swarm_init(machine_id: UUID, payload: SwarmInitRequest):
    try:
        return await swarm_actions_service.init_cluster(
            machine_id=machine_id,
            cluster_name=payload.cluster_name,
        )
    except swarm_actions_service.SwarmActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{machine_id}/actions/swarm_join",
    summary="Join an existing Swarm cluster",
)
async def action_swarm_join(machine_id: UUID, payload: SwarmJoinRequest):
    try:
        return await swarm_actions_service.join_cluster(
            machine_id=machine_id,
            cluster_id=payload.cluster_id,
            role=payload.role,
        )
    except swarm_actions_service.SwarmActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{machine_id}/actions/swarm_leave",
    summary="Leave the Swarm cluster (drops cluster if last node)",
)
async def action_swarm_leave(machine_id: UUID, payload: SwarmLeaveRequest):
    try:
        return await swarm_actions_service.leave_cluster(
            machine_id=machine_id, force=payload.force,
        )
    except swarm_actions_service.SwarmActionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

- [ ] **Step 3 : Smoke import + route enregistrée**

```bash
cd backend && uv run python -c "
from agflow.main import create_app
app = create_app()
paths = sorted({r.path for r in app.routes if 'swarm' in r.path})
for p in paths:
    print(p)
"
```

Attendu : 5 lignes
```
/api/infra/machines/{machine_id}/actions/swarm_init
/api/infra/machines/{machine_id}/actions/swarm_join
/api/infra/machines/{machine_id}/actions/swarm_leave
/api/infra/swarm-clusters
/api/infra/swarm-clusters/{cluster_id}
```

- [ ] **Step 4 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/infra/machines.py
```

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/api/infra/machines.py
git commit -m "feat(api): POST /machines/{id}/actions/swarm_(init|join|leave)

3 endpoints orchestrant les actions Swarm via swarm_actions_service.
Erreurs typees mappees en HTTP 400 via SwarmActionError."
```

---

## Task 9 — Tests d'intégration HTTP

**Files:**
- Create: `backend/tests/test_infra_swarm_clusters_endpoint.py`

- [ ] **Step 1 : Tests d'intégration**

Créer `backend/tests/test_infra_swarm_clusters_endpoint.py` :

```python
"""Tests d'integration HTTP : auth + serialization + bypass services via mocks."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ["AGFLOW_INFRA_KEY"] = "32-byte-key-base64-padded-AAAAAAAAAAAAAA="

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _viewer_token() -> str:
    return jwt.encode(
        {"sub": "viewer@example.com", "role": "viewer"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def test_list_swarm_clusters_requires_token(client: TestClient) -> None:
    r = client.get("/api/infra/swarm-clusters")
    assert r.status_code == 401


def test_list_swarm_clusters_rejects_viewer(client: TestClient) -> None:
    r = client.get(
        "/api/infra/swarm-clusters",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
    )
    assert r.status_code == 403


def test_list_swarm_clusters_returns_list_for_admin(client: TestClient) -> None:
    cluster_id = uuid4()
    fake_clusters = [{
        "id": cluster_id, "name": "swarm1", "manager_addr": "10.0.0.1:2377",
        "node_count": 2, "manager_count": 1, "worker_count": 1,
        "created_at": "2026-04-30T00:00:00Z", "updated_at": "2026-04-30T00:00:00Z",
    }]
    with patch("agflow.api.infra.swarm_clusters.infra_swarm_clusters_service.list_all",
               AsyncMock(return_value=fake_clusters)):
        r = client.get(
            "/api/infra/swarm-clusters",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "swarm1"
    # Aucun token leak
    assert "join_token_worker" not in r.text
    assert "join_token_manager" not in r.text


def test_get_swarm_cluster_404_when_unknown(client: TestClient) -> None:
    with patch("agflow.api.infra.swarm_clusters.infra_swarm_clusters_service.get_by_id",
               AsyncMock(return_value=None)):
        r = client.get(
            f"/api/infra/swarm-clusters/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_swarm_init_success(client: TestClient) -> None:
    cluster_dto = {"id": str(uuid4()), "name": "swarm1", "manager_addr": "10.0.0.1:2377",
                   "created_at": "2026-04-30T00:00:00Z", "updated_at": "2026-04-30T00:00:00Z"}
    with patch("agflow.api.infra.machines.swarm_actions_service.init_cluster",
               AsyncMock(return_value=cluster_dto)):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_init",
            json={"cluster_name": "swarm1"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["name"] == "swarm1"


def test_swarm_init_400_when_action_error(client: TestClient) -> None:
    from agflow.services.swarm_actions_service import SwarmActionError

    with patch("agflow.api.infra.machines.swarm_actions_service.init_cluster",
               AsyncMock(side_effect=SwarmActionError("Machine not swarm-ready"))):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_init",
            json={"cluster_name": "swarm1"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400
    assert "swarm-ready" in r.text


def test_swarm_join_success(client: TestClient) -> None:
    with patch("agflow.api.infra.machines.swarm_actions_service.join_cluster",
               AsyncMock(return_value={"joined": True, "node_id": "n1", "role": "worker"})):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_join",
            json={"cluster_id": str(uuid4()), "role": "worker"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["joined"] is True


def test_swarm_join_400_invalid_role(client: TestClient) -> None:
    r = client.post(
        f"/api/infra/machines/{uuid4()}/actions/swarm_join",
        json={"cluster_id": str(uuid4()), "role": "boss"},
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    # Pydantic validation rejects -> 422
    assert r.status_code == 422


def test_swarm_leave_success(client: TestClient) -> None:
    with patch("agflow.api.infra.machines.swarm_actions_service.leave_cluster",
               AsyncMock(return_value={"left": True, "cluster_dropped": False})):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_leave",
            json={"force": False},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["left"] is True
```

- [ ] **Step 2 : Run**

```bash
cd backend && uv run pytest tests/test_infra_swarm_clusters_endpoint.py -v
```

Attendu : 9 tests verts.

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check tests/test_infra_swarm_clusters_endpoint.py
```

- [ ] **Step 4 : Commit**

```bash
git add backend/tests/test_infra_swarm_clusters_endpoint.py
git commit -m "test(swarm): integration tests pour les endpoints HTTP

9 tests : auth (401/403), liste, 404, swarm_init/join/leave success +
SwarmActionError -> 400, role invalide -> 422 Pydantic. Tokens jamais
exposes dans les payloads de reponse (defense regex)."
```

---

## Task 10 — Vérifs globales

**Files:** Aucun changement de code.

- [ ] **Step 1 : Suite complète des tests B0**

```bash
cd backend && uv run pytest \
  tests/test_infra_machines_ingest.py \
  tests/test_infra_swarm_clusters_service.py \
  tests/test_swarm_actions_service.py \
  tests/test_infra_swarm_clusters_endpoint.py \
  -v
```

Attendu : tous verts (5 + 2 + 8 + 9 = 24 tests).

- [ ] **Step 2 : Régression sur le reste**

```bash
cd backend && uv run pytest \
  tests/test_swarm_defaults.py \
  tests/test_compose_renderer_swarm.py \
  tests/test_compose_renderer_runtime.py \
  tests/test_swarm_secrets.py \
  tests/test_lifespan_db_check.py \
  tests/test_migrations_lock.py \
  tests/test_system_export_service.py \
  tests/test_system_export_endpoint.py \
  -v 2>&1 | tail -3
```

Attendu : tous verts (cumulé des chantiers précédents, ~70 tests).

- [ ] **Step 3 : Lint+format global sur les fichiers touchés**

```bash
cd backend && uv run ruff check \
  src/agflow/schemas/infra.py \
  src/agflow/services/infra_machines_service.py \
  src/agflow/services/infra_swarm_clusters_service.py \
  src/agflow/services/swarm_actions_service.py \
  src/agflow/api/infra/swarm_clusters.py \
  src/agflow/api/infra/machines.py \
  src/agflow/main.py \
  tests/test_infra_machines_ingest.py \
  tests/test_infra_swarm_clusters_service.py \
  tests/test_swarm_actions_service.py \
  tests/test_infra_swarm_clusters_endpoint.py
```

Attendu : `All checks passed!`.

- [ ] **Step 4 : Smoke boot**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('boot ok')"
```

Attendu : `boot ok`.

- [ ] **Step 5 : Liste des commits B0**

```bash
git log --oneline 9282933..HEAD
```

Attendu : 9 commits dans cet ordre :
1. `feat(db): migration 087 - infra_swarm_clusters + colonnes Swarm sur machines`
2. `feat(schemas): SwarmCluster* et CreateLxcOutput pour B0`
3. `feat(infra-machines): helper ingest_creation_output (mapping JSON -> colonnes 1st-class)`
4. `feat(infra-swarm-clusters): service CRUD + tokens Fernet`
5. `feat(swarm-actions): init_cluster (run script + persist cluster + link machine)`
6. `feat(swarm-actions): join_cluster + leave_cluster`
7. `feat(api): GET /api/infra/swarm-clusters (list + detail)`
8. `feat(api): POST /machines/{id}/actions/swarm_(init|join|leave)`
9. `test(swarm): integration tests pour les endpoints HTTP`

- [ ] **Step 6 : `git status -s`**

Attendu : vide.

---

## Critères d'acceptation finaux

- [ ] Migration 087 idempotente, smoke testée sur Postgres 16 LXC 201
- [ ] 8 colonnes 1st-class + 2 Swarm membership sur `infra_machines`
- [ ] 2 CHECK constraints (role + cohérence membership)
- [ ] 3 actions seedées sous catégorie `service`
- [ ] Service `infra_swarm_clusters_service` : tokens chiffrés Fernet, jamais retournés en clair par l'API
- [ ] Service `swarm_actions_service` : 3 actions orchestrant SSH + persistance
- [ ] 5 endpoints API : 2 GET clusters + 3 POST actions machines
- [ ] 24 tests B0 verts, aucune régression
- [ ] Lint propre
- [ ] Boot OK
- [ ] Aucun token Swarm en clair en logs ni en réponses HTTP

---

## Hors plan (rappel)

- Frontend : page Swarm Clusters + enrichissement Machines — plan séparé
- Wiring `ingest_creation_output` dans le mécanisme `infra_named_type_actions` existant — chantier d'enhancement séparé
- Lancement agents Swarm via `aiodocker.services.create` — chantier B1 distinct
- Refacto `container_runner.py` — chantier B2+
- Refacto `group_scripts` post-template-Jinja vers `docker stack deploy` — chantier distinct
- Health checks périodiques des nodes Swarm
- Promotion automatique manager
