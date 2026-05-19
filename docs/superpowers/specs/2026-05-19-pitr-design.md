# Point-In-Time Recovery (PITR) — Design

**Date** : 2026-05-19
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`
**Référence cadrage** : memory `project_pitr_scoping.md` (décisions structurantes du 2026-05-19)

## Objectif

Remplacer le système actuel de snapshots `pg_dump` réguliers (`backup_schedules_snapshot`) par une vraie stratégie **Point-In-Time Recovery** PostgreSQL basée sur **pgBackRest** : basebackup quotidien + archivage continu des WAL, permettant à l'admin de restaurer la base à n'importe quelle minute précise dans la fenêtre disponible.

Le `pg_dump` complet planifié reste en place pour l'archive long terme portable (table `backup_schedules_full` inchangée).

## Contexte

L'app a actuellement :
- Un système `backup_schedules_full` (cron `pg_dump`) — conservé tel quel.
- Un système `backup_schedules_snapshot` (interval `pg_dump` plus court) — **à supprimer**.
- Image Postgres standard `postgres:16-alpine`.
- Pas d'archivage WAL, pas de PITR.

Les snapshots `pg_dump` à intervalle court ne permettent pas une restauration fine : RPO = intervalle (15 min à plusieurs heures), perte garantie de toute donnée écrite après le dernier snapshot. Pas adapté pour une plateforme qui héberge l'état des agents IA.

## Décisions structurantes (figées en brainstorming)

| # | Axe | Décision | Rationale |
|---|---|---|---|
| 1 | Stack | **pgBackRest** | Production-grade, retention auto, compression incrémentale, support cloud natif, image Alpine disponible (paquet `pgbackrest`). |
| 2 | Intégration | **Image custom postgres+pgBackRest** | Tout dans le même container : `archive_command` local, configuration centralisée, simple à déployer. |
| 3 | WAL retention | **Local seul, bornée par oldest basebackup** | RPO ≤ 24h en cas de crash LXC accepté. Pas de push WAL temps réel vers le cloud (complexité non justifiée). |
| 4 | Basebackup | **Quotidien fixe (3h du matin) + push vers N remotes** | Cadence prévisible, multi-destination pour résilience disaster recovery. |
| 5 | Restore mode | **Clone (Postgres temporaire à côté)** | Pas de downtime sur l'app live, l'admin peut inspecter / extraire avant toute action destructive. |
| 6 | Granularité picker | **À la minute** | Suffisant pour les scénarios réels, UX simple, format natif pgBackRest. |
| 7 | Timezone | **Fuseau local du navigateur** | Friction mentale minimale pour l'admin. Conversion en UTC côté client avant l'appel API. |
| 8 | Clone | **1 seul à la fois, TTL 24h, accès via pgweb embarqué** | Borne l'utilisation disque, simple côté backend, accès SQL libre via pgweb pour inspection + export CSV. |
| 9 | Migration snapshots existants | **Drop net** | Aucun environnement de prod actuellement, LXC réinstancié à chaque test. Pas de besoin de soft-delete. |

## Architecture d'ensemble

```
┌──────────────────── LXC 201 ──────────────────────────────────────────┐
│                                                                       │
│  ┌─ agflow-postgres (image custom) ────────────────────────┐          │
│  │  postgres 16-alpine + pgBackRest                        │          │
│  │  archive_mode=on, wal_level=replica                     │          │
│  │  archive_command = pgbackrest archive-push %p           │          │
│  │  Volumes: postgres_data + pgbackrest_repo               │          │
│  └─────────────────────────────────────────────────────────┘          │
│                  ▲ (exec via aiodocker)                               │
│                  │                                                    │
│  ┌─ agflow-backend ─────────────────────────────────────────┐         │
│  │  FastAPI                                                  │         │
│  │  ├── services/pitr_basebackup_service.py    (CRUD + push) │         │
│  │  ├── services/pitr_restore_service.py       (clone+pgweb) │         │
│  │  ├── services/pitr_clone_service.py         (TTL, état)   │         │
│  │  ├── services/pitr_wal_archive_service.py   (état WAL)    │         │
│  │  ├── services/pitr_scheduler.py             (cron+TTL)    │         │
│  │  └── api/admin/pitr.py                      (REST)        │         │
│  └───────────────────────────────────────────────────────────┘         │
│                                                                       │
│  ┌─ agflow-pitr-clone-<uuid> (éphémère) ───────────────────┐          │
│  │  postgres restauré à T-Δ via pgbackrest restore         │          │
│  │  Réseau Docker dédié 'pitr-clone-net-<uuid>'            │          │
│  └─────────────────────────────────────────────────────────┘          │
│                                                                       │
│  ┌─ agflow-pitr-pgweb-<uuid> (éphémère) ──────────────────┐           │
│  │  sosedoff/pgweb → connecté au clone                    │           │
│  │  Exposé sur LAN port aléatoire                         │           │
│  └─────────────────────────────────────────────────────────┘          │
│                                                                       │
│  ┌─ agflow-frontend ─────────────────────────────────────────┐        │
│  │  Page Backups :                                            │        │
│  │  ├── Section Full pg_dump (existante, inchangée)           │        │
│  │  ├── Section PITR (nouvelle)                               │        │
│  │  │   ├── État WAL (archiving + dernière archive)          │        │
│  │  │   ├── Liste basebackups (jour, taille, pushes remote)  │        │
│  │  │   ├── Datetime picker → "Restaurer (clone)"            │        │
│  │  │   └── Clone actif (état, pgweb link, stop, extend)     │        │
│  │  └── Section Local backups (filtre source adapté)          │        │
│  └───────────────────────────────────────────────────────────┘        │
└───────────────────────────────────────────────────────────────────────┘
```

**Composants ajoutés** :
- Image custom `agflow-postgres:16-pitr` (Dockerfile dans `infra/postgres-pitr/`)
- 4 services Python SRP + 1 worker APScheduler + 1 router REST
- 5 tables DB : `pitr_basebackups`, `pitr_basebackup_pushes`, `pitr_config` (singleton), `pitr_config_remotes` (join), `pitr_clones`
- 8 composants frontend

**Composants retirés** :
- Table `backup_schedules_snapshot`, colonne `local_backups.source_schedule_snapshot_id`
- `SnapshotSchedulesSection.tsx`
- Logique snapshot dans `backup_scheduler.py` et `backup_job_runner.py`
- i18n keys `backups.schedules.snapshot*`, `colInterval`, `addSnapshot`, etc.

## Modèle de données

### Migration 110 — `backend/migrations/110_pitr.sql`

```sql
-- 110_pitr.sql — PITR (Point-In-Time Recovery via pgBackRest)

CREATE TABLE pitr_basebackups (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pgbackrest_label        text NOT NULL UNIQUE,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    size_bytes              bigint,
    status                  text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    error                   text,
    recovery_window_start   timestamptz,
    recovery_window_end     timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_pitr_basebackups_started_at ON pitr_basebackups (started_at DESC);
CREATE INDEX idx_pitr_basebackups_status ON pitr_basebackups (status) WHERE status = 'running';

CREATE TABLE pitr_basebackup_pushes (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    basebackup_id           uuid NOT NULL REFERENCES pitr_basebackups(id) ON DELETE CASCADE,
    remote_connection_id    uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    status                  text NOT NULL CHECK (status IN ('pending', 'pushing', 'ok', 'failed')),
    pushed_at               timestamptz,
    error                   text,
    remote_path             text,
    size_bytes              bigint,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (basebackup_id, remote_connection_id)
);

CREATE INDEX idx_pitr_pushes_basebackup ON pitr_basebackup_pushes (basebackup_id);
CREATE INDEX idx_pitr_pushes_remote ON pitr_basebackup_pushes (remote_connection_id);

CREATE TABLE pitr_config (
    id                      int PRIMARY KEY CHECK (id = 1),
    enabled                 boolean NOT NULL DEFAULT true,
    basebackup_cron         text NOT NULL DEFAULT '0 3 * * *',
    retention_count         int NOT NULL DEFAULT 7 CHECK (retention_count >= 1),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pitr_config_remotes (
    config_id               int NOT NULL REFERENCES pitr_config(id) ON DELETE CASCADE,
    remote_connection_id    uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    PRIMARY KEY (config_id, remote_connection_id)
);

CREATE TABLE pitr_clones (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    basebackup_id           uuid NOT NULL REFERENCES pitr_basebackups(id) ON DELETE RESTRICT,
    target_time             timestamptz NOT NULL,
    status                  text NOT NULL CHECK (status IN ('restoring', 'ready', 'terminating', 'terminated', 'failed')),
    error                   text,
    postgres_container_id   text,
    postgres_container_name text,
    pgweb_container_id      text,
    pgweb_container_name    text,
    pgweb_port              int,
    started_at              timestamptz NOT NULL DEFAULT now(),
    ready_at                timestamptz,
    expires_at              timestamptz NOT NULL,
    terminated_at           timestamptz,
    created_by_user_id      uuid REFERENCES users(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX idx_pitr_clones_one_active
    ON pitr_clones (id)
    WHERE status IN ('restoring', 'ready', 'terminating');

CREATE INDEX idx_pitr_clones_status ON pitr_clones (status);
CREATE INDEX idx_pitr_clones_expires_at ON pitr_clones (expires_at) WHERE status IN ('restoring', 'ready');

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pitr_pushes_updated_at') THEN
        CREATE TRIGGER trg_pitr_pushes_updated_at
            BEFORE UPDATE ON pitr_basebackup_pushes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pitr_config_updated_at') THEN
        CREATE TRIGGER trg_pitr_config_updated_at
            BEFORE UPDATE ON pitr_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

INSERT INTO pitr_config (id, enabled, basebackup_cron, retention_count)
VALUES (1, true, '0 3 * * *', 7)
ON CONFLICT (id) DO NOTHING;
```

### Migration 111 — `backend/migrations/111_drop_snapshot_schedules.sql`

```sql
ALTER TABLE local_backups DROP CONSTRAINT IF EXISTS local_backups_source_single;
ALTER TABLE local_backups DROP COLUMN IF EXISTS source_schedule_snapshot_id;
DROP TABLE IF EXISTS backup_schedules_snapshot;
```

### Notes de design

- **Pas de table `pitr_schedules` (pluriel)** : une seule planif active possible (WAL streaming continu = un seul `archive_command`). Table singleton `pitr_config` avec PK fixe `1`.
- **Push N remotes** modélisé via `pitr_config_remotes` (config → liste de remotes) + `pitr_basebackup_pushes` (1 ligne par tentative).
- **Index unique partiel `idx_pitr_clones_one_active`** garantit côté DB l'unicité du clone actif. Le code ne peut pas se planter là-dessus.
- **`recovery_window_end` mis à jour à chaque archive WAL** via `pitr_wal_archive_service.refresh_recovery_windows()` (cron 5 min). Permet à l'UI d'afficher le bornage exact du datetime picker.

## API REST

Router `backend/src/agflow/api/admin/pitr.py`, préfixe `/api/admin/pitr`, `require_admin` global.

| Méthode | Path | Action | Codes |
|---|---|---|---|
| GET | `/config` | lit `pitr_config` + remotes liés | 401/403 |
| PUT | `/config` | update cron, retention_count, enabled, remote_connection_ids | 422, 404 |
| GET | `/basebackups` | liste basebackups avec pushes agrégés + fenêtre globale | 401/403 |
| GET | `/basebackups/{id}` | détail basebackup + tous ses pushes | 404 |
| POST | `/basebackups` | déclenche un basebackup immédiat | 409 si déjà en cours |
| DELETE | `/basebackups/{id}` | supprime (pgbackrest expire + pushes cascade) | 404, 409 si seul restant |
| POST | `/basebackups/{id}/push/{remote_id}` | re-push manuel | 404, 409 |
| GET | `/wal-status` | archiving actif, last archived, disk used/free | 401/403 |
| GET | `/restore-window` | borne `[earliest, latest]` UTC | 404 si aucun basebackup OK |
| POST | `/clones` | lance restore vers clone éphémère | 409 si actif, 422 hors fenêtre |
| GET | `/clones/active` | état du clone actif (`null` si aucun) | 401/403 |
| POST | `/clones/active/extend` | rallonge `expires_at` de +24h | 404, 409 |
| DELETE | `/clones/active` | arrête + supprime containers + volume | 404 |

**13 endpoints au total.**

### Schémas Pydantic (extraits)

```python
class PitrConfigOut(BaseModel):
    enabled: bool
    basebackup_cron: str
    retention_count: int
    remote_connection_ids: list[UUID]
    updated_at: datetime

class BasebackupPushSummary(BaseModel):
    remote_connection_id: UUID
    remote_connection_name: str
    status: Literal["pending", "pushing", "ok", "failed"]
    pushed_at: datetime | None
    error: str | None
    size_bytes: int | None

class BasebackupSummary(BaseModel):
    id: UUID
    pgbackrest_label: str
    started_at: datetime
    completed_at: datetime | None
    size_bytes: int | None
    status: Literal["running", "ok", "failed"]
    error: str | None
    recovery_window_start: datetime | None
    recovery_window_end: datetime | None
    pushes: list[BasebackupPushSummary]

class WalStatus(BaseModel):
    archiving_enabled: bool
    last_archived_at: datetime | None
    archive_lag_seconds: int | None
    wal_disk_used_bytes: int
    wal_disk_free_bytes: int

class RestoreWindow(BaseModel):
    earliest: datetime
    latest: datetime

class CloneRequest(BaseModel):
    target_time: datetime    # ISO8601 UTC

class CloneStatus(BaseModel):
    id: UUID
    basebackup_id: UUID
    basebackup_label: str
    target_time: datetime
    status: Literal["restoring", "ready", "terminating", "terminated", "failed"]
    error: str | None
    pgweb_url: str | None
    started_at: datetime
    ready_at: datetime | None
    expires_at: datetime
    expires_in_seconds: int
```

### Validation

- `basebackup_cron` : validé via `croniter(expr)` → 422 si invalide
- `target_time` : doit être dans `[earliest, latest]` → 422 explicite
- `remote_connection_ids` : chaque UUID doit exister → 404
- 409 sur toutes les races (basebackup déjà en cours, clone déjà actif, push déjà OK)

## Services backend

### `pitr_basebackup_service.py` (~180 lignes)

```python
async def list_basebackups() -> list[BasebackupSummary]
async def get_basebackup(id: UUID) -> BasebackupSummary
async def trigger_basebackup_now(actor_user_id: UUID | None) -> UUID
async def delete_basebackup(id: UUID) -> None
async def push_basebackup(basebackup_id: UUID, remote_id: UUID) -> None
async def _push_to_remotes(basebackup_id: UUID) -> None
async def _prune_old_basebackups(retention_count: int) -> int
async def ensure_stanza() -> None  # appelé au lifespan, idempotent
```

`trigger_basebackup_now` flow :
1. INSERT row status=`running`
2. `aiodocker.exec(postgres_container, ['pgbackrest', '--stanza=agflow', 'backup', '--type=full'])`
3. Parse stdout pour récupérer le label
4. UPDATE row (status=`ok`, completed_at, label, size_bytes)
5. INSERT 1 row `pitr_basebackup_pushes` (status=`pending`) par remote dans `pitr_config_remotes`
6. Background : `_push_to_remotes(basebackup_id)` (séquentiel par basebackup)
7. Background : `_prune_old_basebackups(retention_count)`

Exceptions : `BasebackupRunningError` (409), `BasebackupNotFoundError` (404), `BasebackupIsLastError` (409), `PushAlreadyOkError` (409).

### `pitr_restore_service.py` (~200 lignes)

```python
async def get_restore_window() -> RestoreWindow
async def start_clone(target_time: datetime, actor_user_id: UUID | None) -> UUID
async def _provision_clone(clone_id: UUID) -> None  # background
```

`start_clone` flow :
1. Valide `target_time ∈ [earliest, latest]` → `InvalidTargetTimeError`
2. Vérifie absence de clone actif → `CloneAlreadyActiveError`
3. Choisit le plus ancien basebackup OK dont `recovery_window_end >= target_time`
4. INSERT row `pitr_clones` (status=`restoring`, `expires_at = now() + 24h`)
5. Lance `_provision_clone(clone_id)` en background → retourne UUID immédiatement

`_provision_clone` :
- Crée volume Docker `agflow-pitr-clone-data-<uuid8>`
- Crée réseau Docker `pitr-clone-net-<uuid8>`
- Crée container postgres clone (image `agflow-postgres:16-pitr` en mode `restore` via env vars), montage du repo en read-only
- Wait healthcheck (`pg_isready`, timeout 5 min)
- Crée container pgweb connecté au clone
- UPDATE row (status=`ready`, container IDs, pgweb_port, ready_at)
- Try/except global : si erreur → UPDATE status=`failed` + nettoie tout

Exceptions : `RestoreWindowEmptyError` (404), `InvalidTargetTimeError` (422), `CloneAlreadyActiveError` (409).

### `pitr_clone_service.py` (~120 lignes)

```python
async def get_active_clone() -> CloneStatus | None
async def extend_active_clone() -> CloneStatus
async def terminate_active_clone() -> None
async def cleanup_expired_clones() -> int  # appelé par scheduler 1×/h
```

`terminate_active_clone` :
1. UPDATE status=`terminating`
2. aiodocker stop + remove des 2 containers
3. Drop volume
4. Drop réseau Docker
5. UPDATE status=`terminated`, terminated_at

`cleanup_expired_clones` scan aussi les containers / volumes / réseaux orphelins (pattern de nom `agflow-pitr-clone-*`, `pitr-clone-net-*`) — robustesse aux crashs backend.

### `pitr_wal_archive_service.py` (~80 lignes)

```python
async def get_wal_status() -> WalStatus
async def refresh_recovery_windows() -> int  # cron 5 min
```

`get_wal_status` :
- `aiodocker.exec(['pgbackrest', '--stanza=agflow', 'info', '--output=json'])` → parse JSON
- `df -B 1 /var/lib/pgbackrest` via aiodocker.exec → disk used/free
- `SELECT pg_settings WHERE name='archive_mode'` via asyncpg → archiving_enabled

`refresh_recovery_windows` : pour chaque basebackup `status='ok'`, met à jour `recovery_window_end = max(timestamp dernière archive WAL)`.

### `pitr_scheduler.py` (~100 lignes)

Worker APScheduler dédié, indépendant de `backup_scheduler.py`.

```python
async def start() -> None
async def reload_basebackup_schedule() -> None  # appelé après PUT /config si cron change
async def stop() -> None
```

3 jobs APScheduler :
- `_run_daily_basebackup` (cron depuis `pitr_config.basebackup_cron`)
- `_run_clone_cleanup` (interval 1h) → `pitr_clone_service.cleanup_expired_clones()`
- `_run_wal_refresh` (interval 5 min) → `pitr_wal_archive_service.refresh_recovery_windows()`

`max_instances=1` + `coalesce=True` sur le basebackup. Attaché au loop FastAPI via `main.lifespan`.

### Intégration `main.py` lifespan

```python
from agflow.services.pitr_scheduler import start as _pitr_start, stop as _pitr_stop
from agflow.services.pitr_basebackup_service import ensure_stanza as _pitr_ensure_stanza

async def lifespan(app):
    # ... init existant ...
    await _pitr_ensure_stanza()
    await _pitr_start()
    yield
    await _pitr_stop()
```

## Image custom Postgres + pgBackRest

### Dockerfile — `infra/postgres-pitr/Dockerfile`

```dockerfile
FROM postgres:16-alpine

RUN apk add --no-cache pgbackrest

RUN mkdir -p /var/lib/pgbackrest /etc/pgbackrest /var/log/pgbackrest \
 && chown -R postgres:postgres /var/lib/pgbackrest /var/log/pgbackrest \
 && chmod 750 /var/lib/pgbackrest /var/log/pgbackrest

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY postgresql-pitr.conf /etc/postgresql/postgresql-pitr.conf
COPY docker-entrypoint-pitr.sh /usr/local/bin/docker-entrypoint-pitr.sh

RUN chmod +x /usr/local/bin/docker-entrypoint-pitr.sh \
 && chown postgres:postgres /etc/pgbackrest/pgbackrest.conf

ENTRYPOINT ["docker-entrypoint-pitr.sh"]
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql-pitr.conf"]
```

### `pgbackrest.conf`

```ini
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=7
repo1-cipher-type=none
compress-type=zst
compress-level=3
process-max=2
log-level-console=info
log-level-file=detail
log-path=/var/log/pgbackrest
start-fast=y

[agflow]
pg1-path=/var/lib/postgresql/data
pg1-port=5432
pg1-user=postgres
pg1-database=postgres
```

### `postgresql-pitr.conf`

```ini
archive_mode = on
archive_command = 'pgbackrest --stanza=agflow archive-push %p'
wal_level = replica
max_wal_senders = 3
archive_timeout = 60
include_if_exists = '/var/lib/postgresql/data/postgresql.conf'
```

### `docker-entrypoint-pitr.sh`

```bash
#!/bin/sh
set -eu

if [ "${AGFLOW_PITR_MODE:-normal}" = "restore" ]; then
    : "${AGFLOW_PITR_TARGET_TIME:?required}"
    echo "[pitr] Restore mode: target=${AGFLOW_PITR_TARGET_TIME}"
    pgbackrest --stanza=agflow restore \
        --type=time \
        --target="${AGFLOW_PITR_TARGET_TIME}" \
        --target-action=promote \
        --pg1-path=/var/lib/postgresql/data
    exec docker-entrypoint.sh "$@"
fi

exec docker-entrypoint.sh "$@"
```

**Note** : `pgbackrest stanza-create` n'est PAS dans l'entrypoint (fragile). Il est exécuté de manière idempotente par `pitr_basebackup_service.ensure_stanza()` au lifespan backend.

### Modif `docker-compose.dev.yml`

```yaml
services:
  postgres:
    image: agflow-postgres:16-pitr
    build:
      context: ./infra/postgres-pitr
      dockerfile: Dockerfile
    container_name: agflow-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-agflow}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?postgres password required}
      POSTGRES_DB: ${POSTGRES_DB:-agflow}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - pgbackrest_repo:/var/lib/pgbackrest
      - pgbackrest_logs:/var/log/pgbackrest
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      retries: 5
    networks: [agflow]

volumes:
  postgres_data:
  pgbackrest_repo:
  pgbackrest_logs:
  caddy_data:
  caddy_config:
```

### Premier déploiement

1. Build image : `docker compose build postgres` sur LXC 201
2. Restart Postgres (downtime ~30s — seul moment inévitable)
3. `ensure_stanza()` exécutée par backend au lifespan → crée la stanza
4. Premier basebackup : `POST /api/admin/pitr/basebackups` OU attendre 3h
5. Validation : `GET /api/admin/pitr/wal-status` doit retourner `archiving_enabled: true`, `last_archived_at` ≠ null

## Frontend

### Composants nouveaux

| Composant | Rôle | LoC approx |
|---|---|---|
| `components/backups/PitrSection.tsx` | Conteneur principal | ~120 |
| `components/backups/WalArchiveStatus.tsx` | Badge état archive | ~80 |
| `components/backups/RecoveryWindowChart.tsx` | Barre visuelle `[earliest ─── latest]` | ~90 |
| `components/backups/BasebackupsList.tsx` | Tableau basebackups + pushes + actions | ~180 |
| `components/backups/BasebackupActionsMenu.tsx` | DropdownMenu (delete, re-push, détails) | ~70 |
| `components/backups/PitrRestoreForm.tsx` | Date + time picker + bouton restaurer | ~150 |
| `components/backups/ActiveCloneCard.tsx` | Carte clone (état, expires, prolonger, stop, pgweb) | ~140 |
| `components/backups/PitrConfigDialog.tsx` | Dialog ⚙ (cron + retention + multi-select remotes) | ~180 |

### Composants modifiés / supprimés

- ❌ Supprimé : `SnapshotSchedulesSection.tsx`
- ❌ Supprimé : `ScheduleHistoryTable.tsx` (si lié aux snapshots uniquement)
- ✏️ Modifié : `pages/BackupsPage.tsx` (ajout `<PitrSection />`, retrait `<SnapshotSchedulesSection />`)
- ✏️ Modifié : `LocalBackupsSection` (filtre source réduit à 3 options)

### API client + hooks

**Nouveau** `frontend/src/lib/pitrApi.ts` (~180 lignes) — exporte `pitrApi.{getConfig, updateConfig, listBasebackups, getBasebackup, triggerBasebackup, deleteBasebackup, pushBasebackup, getWalStatus, getRestoreWindow, getActiveClone, startClone, extendActiveClone, terminateActiveClone}`.

**Nouveau** `frontend/src/hooks/usePitr.ts` (~140 lignes) — `usePitrConfig`, `usePitrBasebackups` (refetch 30s), `usePitrWalStatus` (10s), `usePitrRestoreWindow` (30s), `usePitrActiveClone` (2s si restoring/terminating, 30s si ready, off si terminated/failed).

### Datetime picker

Inputs natifs HTML5 :

```tsx
<input type="date" min={minDate} max={maxDate} value={dateStr} />
<input type="time" min={...} max={...} value={timeStr} step="60" />
```

Conversion timezone côté client :

```typescript
const localISO = `${date}T${time}:00`;
const utcDate = new Date(localISO);
const utcISO = utcDate.toISOString();
await pitrApi.startClone({ target_time: utcISO });
```

Label statique sous le picker :
> Fuseau saisie : `Intl.DateTimeFormat().resolvedOptions().timeZone` (UTC{±H}) · serveur reçoit : `2026-05-19T13:32:00Z`

### Confirmation avant restore

Dialog shadcn (jamais `window.confirm` — cf. memory `feedback_no_system_prompt.md`) :

> **Restaurer à `2026-05-19 14:32` (Europe/Paris) ?**
>
> Un clone Postgres temporaire va être créé à partir du basebackup `20260519-030000F` et restauré jusqu'à ce point.
>
> - La base de données live **n'est pas affectée**.
> - L'opération prend généralement 1 à 3 minutes.
> - Le clone sera accessible via pgweb pendant **24h** (prolongeable).
> - Un seul clone peut exister à la fois — si un clone précédent est actif, il sera arrêté.

### i18n

**~55 clés ajoutées** sous `backups.pitr.*` (FR + EN) :
- `pitr.title`, `pitr.subtitle`
- `pitr.wal.archivingActive/Inactive`, `pitr.wal.lastArchived`, `pitr.wal.diskUsage`
- `pitr.window.title`, `pitr.window.earliest`, `pitr.window.latest`, `pitr.window.empty`
- `pitr.basebackups.title`, `pitr.basebackups.empty`, `pitr.basebackups.triggerNow`, `pitr.basebackups.colDate/Size/Pushes/Actions`, `pitr.basebackups.pushOk/Pending/Failed`, `pitr.basebackups.deleteConfirm`
- `pitr.restore.title`, `pitr.restore.dateLabel`, `pitr.restore.timeLabel`, `pitr.restore.timezoneHint`, `pitr.restore.button`, `pitr.restore.confirmTitle/Description`, `pitr.restore.outOfWindowError`
- `pitr.clone.none`, `pitr.clone.ready/Restoring/Terminating/Failed`, `pitr.clone.expiresIn`, `pitr.clone.extendButton`, `pitr.clone.stopButton`, `pitr.clone.openPgweb`
- `pitr.config.title`, `pitr.config.cron`, `pitr.config.retention`, `pitr.config.remotes`, `pitr.config.save`

**~15 clés retirées** : toutes celles `backups.schedules.snapshot*`, `colInterval`, `addSnapshot`, `formIntervalLabel`, `formIntervalAmount`, `formIntervalUnit`, etc.

## Tests

### Backend (~75 tests Python)

| Fichier | Type | Coverage |
|---|---|---|
| `tests/services/test_pitr_basebackup_service.py` | unit + integration DB | ~95% |
| `tests/services/test_pitr_restore_service.py` | integration DB + mock aiodocker | ~90% |
| `tests/services/test_pitr_clone_service.py` | integration DB + mock aiodocker | ~90% |
| `tests/services/test_pitr_wal_archive_service.py` | mock aiodocker.exec | ~85% |
| `tests/services/test_pitr_scheduler.py` | mock AsyncIOScheduler | ~80% |
| `tests/api/test_admin_pitr.py` | integration HTTP | ~95% |
| `tests/db/test_migration_111_drop_snapshot.py` | unit migration | 100% |

### Frontend (~25 tests Vitest)

- `usePitr.test.ts` — mocks api, refetchInterval selon status
- `PitrRestoreForm.test.tsx` — conversion timezone, bornes min/max
- `BasebackupsList.test.tsx` — rendu pushes mixtes, actions
- `ActiveCloneCard.test.tsx` — rendu selon status, countdown
- `RecoveryWindowChart.test.tsx` — rendu barre, état vide

### E2E — étape 7.10 dans `./scripts/run-test.sh`

Séquence chronologique (préparation + 9 assertions `fail`) :

| # | Action | Assertion `fail` si... |
|---|---|---|
| 1 | Vérifier stanza pgbackrest au boot | `pgbackrest info` ne contient pas `agflow` |
| 2 | `POST /pitr/basebackups` | UUID retourné vide |
| 3 | Polling status (timeout 3 min) | `status != 'ok'` |
| 4 | INSERT canary `before` + switch WAL + note `T_BEFORE` + INSERT canary `after` + switch WAL | (setup, pas d'assertion) |
| 5 | `POST /pitr/clones` avec `target_time=T_BEFORE` | UUID retourné vide |
| 6 | Polling status (timeout 5 min) | `status != 'ready'` |
| 7 | `psql` sur le clone : `COUNT(*) WHERE note='before'` | `≠ 1` |
| 8 | `psql` sur le clone : `COUNT(*) WHERE note='after'` | `≠ 0` |
| 9 | `DELETE /pitr/clones/active` puis `docker ps --filter name=agflow-pitr-clone-*` | trouve encore des containers |
| 10 | `psql` sur la DB live : `COUNT(*) WHERE note='before'` | `≠ 1` |
| 11 | `psql` sur la DB live : `COUNT(*) WHERE note='after'` | `≠ 1` |

### Tests retirés (~25)

- `tests/services/test_backup_schedules_service.py` — section snapshot
- `tests/api/test_admin_backup_schedules.py` — endpoints `/snapshot`
- `tests/services/test_backup_job_runner.py` — `run_snapshot_job`

**Net : +75 tests ajoutés, -25 retirés, +50 net.**

## Découpage en phases

| Phase | Périmètre | Livrables | Effort |
|---|---|---|---|
| **P1 — Image custom Postgres** | Dockerfile + configs + entrypoint + modif compose + volume | Build OK, archiving actif | 3-4j |
| **P2 — Migrations + services backend** | Migrations 110, 111 + 4 services Python + tests unit | Services SRP <200 LoC chacun, ~50 tests verts | 5-6j |
| **P3 — Worker + API REST** | pitr_scheduler.py + api/admin/pitr.py + lifespan + tests intégration | 13 endpoints, ~25 tests HTTP verts | 2-3j |
| **P4 — Frontend** | API client + hooks + 8 composants + dialogs + i18n | Page Backups refondue, picker fonctionnel | 3-4j |
| **P5 — Nettoyage** | Retrait code snapshot, tests obsolètes, i18n keys | No dead code | 1-2j |
| **P6 — E2E + smoke** | Étape 7.10 run-test.sh + validation manuelle | Step 7.10 ✅ | 2-3j |

**Total : 16-22 jours** (≈ 2.5-3 semaines avec parallélisme P2/P4 via subagents).

## Risques résiduels

| Risque | Mitigation |
|---|---|
| Build image custom à chaque restart LXC | Image taggée et cachée dans Docker du LXC. CI build une fois. |
| Race `pgbackrest stanza-create` au premier boot | `ensure_stanza()` côté backend, idempotent. |
| Conflit FS sur `/var/lib/pgbackrest` (clone vs main) | Volume monté en read-only dans le clone. |
| Réseau Docker orphelin si crash backend | `cleanup_expired_clones` scanne le pattern `pitr-clone-net-*`. |
| Volume éphémère orphelin | Idem : scan `agflow-pitr-clone-data-*`. |
| `archive_command` qui échoue silencieusement | Healthcheck `/health/pitr` + alerte Loki. |
| `target_time` au milieu d'une transaction | Postgres restore s'arrête à la dernière transaction complète ≤ target. Documenté dans tooltip. |
| Image custom oubliée au build après PR | `./scripts/deploy.sh --rebuild`. Assertion run-test.sh sur date image. |
| Push N×N latence | Pushes séquentiels par basebackup, parallèles entre basebackups. UI temps réel. |
| Compatibilité postgres 16 → 17 future | Hors scope V1, documenté. |

## Critères d'acceptation V1

- [ ] `pgbackrest --stanza=agflow info` retourne au moins 1 basebackup OK
- [ ] WAL archiving actif en continu, `archive_lag < 90s` en régime nominal
- [ ] Basebackup quotidien observé sans intervention pendant 3 jours consécutifs
- [ ] Restauration via clone : démarre, contient les données à T-Δ, accessible via pgweb, DB live non affectée
- [ ] Suppression du clone : containers + volume + réseau retirés
- [ ] TTL 24h fonctionne (clone forcé en `terminated` après expiration)
- [ ] Push d'un basebackup vers ≥ 2 remotes en parallèle
- [ ] Aucune trace de `backup_schedules_snapshot` dans le code, la DB, l'UI, les i18n keys
- [ ] `./scripts/run-test.sh` passe les 8 assertions historiques + les 9 assertions de l'étape 7.10 PITR

## Out-of-scope V1 (différé V2)

- ❌ Plusieurs clones simultanés
- ❌ Restauration in-place (option à ajouter si besoin réel)
- ❌ Export sélectif (`pg_dump` partiel) depuis le clone via UI dédiée
- ❌ Notifications email/webhook sur échec basebackup ou push remote
- ❌ Encryption pgBackRest (`repo1-cipher-type`) — à activer plus tard avec Harpocrate
- ❌ Push WAL temps-réel vers cloud (RPO < 24h)
- ❌ Compression `repo1-bundle=y` (gain ~30% sur petits backups)
- ❌ Restauration multi-bases (restore = cluster entier)

## Conventions de commit

- `feat(pitr-infra):` — Dockerfile, configs pgBackRest, compose
- `feat(pitr-db):` — migrations 110, 111
- `feat(pitr-services):` — services Python
- `feat(pitr-scheduler):` — worker APScheduler
- `feat(pitr-api):` — router admin
- `feat(pitr-ui):` — frontend
- `chore(pitr):` — cleanup snapshot
- `test(pitr):` — étape 7.10 run-test.sh
- `docs(pitr):` — éventuel guide admin

## Prochaine étape

Plan d'implémentation TDD détaillé via la skill `superpowers:writing-plans`, qui découpera les 6 phases en tâches red/green/refactor exécutables une par une.
