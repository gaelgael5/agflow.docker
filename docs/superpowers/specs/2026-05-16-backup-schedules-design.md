# Planifications de backups (full cron + snapshot interval)

**Date** : 2026-05-16
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Permettre à l'admin de planifier deux types de backups depuis la page Backups :

- **Schedules « full »** déclenchés par expression cron (ex: dump quotidien à 3h)
- **Schedules « snapshot »** déclenchés par intervalle court (ex: toutes les 15 min ou toutes les heures)

Chaque schedule peut optionnellement pousser le backup résultant vers une `remote_backup_connection` configurée (sftp/s3/ftps/gdrive). La rétention locale est bornée par schedule (`retention_count` derniers backups conservés).

Le worker actuel `remote_backup_pusher` (1 backup partagé pour toutes les connexions snapshots, tick 5 min hardcodé) est **remplacé** par un scheduler unifié basé sur APScheduler qui consomme les deux tables.

## Contexte

L'app a actuellement :
- Une table `local_backups` (id, filename, file_path, size_bytes, status, created_at, created_by_user_id) — pas de notion de `kind` (full/snapshot).
- Un service `local_backups_service.create_backup()` qui fait le dump Postgres + écrit le fichier + INSERT row.
- Une table `remote_backup_connections` (kind sftp/s3/ftps/gdrive) avec configuration (`config` JSONB) qui définit déjà un path `snapshots/` et un path `full/` (résolus via `resolve_remote_path(config, kind, "full"|"snapshots")`).
- Un worker `remote_backup_pusher` (5 min tick) qui crée UN backup partagé et le pousse vers toutes les connexions ayant un `snapshots` path. Pas de planification configurable, pas de rétention.
- Une page Backups frontend (`BackupsPage.tsx`) qui affiche la liste des backups locaux + section connexions distantes via composants existants (`LocalBackupsSection`, `RemoteBackupsBrowser`).

Pas de schedule en DB, pas de cron, pas de bouton « créer un backup maintenant ».

## Décisions structurantes (tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Modèle table schedules | **2 tables séparées** : `backup_schedules_full` (cron) + `backup_schedules_snapshot` (interval) | Cohérent avec la séparation déjà existante `resolve_remote_path("full"|"snapshots")`. UX plus claire avec 2 sections distinctes dans la page. |
| 2 | Format interval snapshot | **`interval_amount int` + `interval_unit enum 'minutes'|'hours'`** | Préserve l'intention utilisateur (« 6 heures » au lieu de « 360 minutes »). Le worker convertit en delta interne. |
| 3 | Worker / scheduler | **APScheduler (AsyncIOScheduler)** | Lib mature, gère cron + interval nativement, `max_instances=1` natif. Jobstore RAM (notre DB est la source de vérité). |
| 4 | Rétention | **`retention_count int` par schedule** + `source_schedule_*_id` sur `local_backups` | Borne déterministe. Permet de pruner « les N derniers déclenchés par CE schedule ». Snapshots et fulls n'ont pas la même politique. |
| 5 | UX manuelle | **Toggle `enabled` + bouton « Run now »** | Couvre les 2 cas (pause sans perdre la config + tester un schedule fraîchement créé). |

## Modèle de données

### Migration 109 — `backend/migrations/109_backup_schedules.sql`

```sql
-- 109_backup_schedules.sql — Planifications de backups (full cron + snapshot interval)

CREATE TABLE backup_schedules_full (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  text NOT NULL,
    cron_expr             text NOT NULL,                      -- ex: '0 3 * * *'
    remote_connection_id  uuid REFERENCES remote_backup_connections(id) ON DELETE SET NULL,
    retention_count       int  NOT NULL DEFAULT 10 CHECK (retention_count >= 1),
    enabled               boolean NOT NULL DEFAULT true,
    last_run_at           timestamptz,
    last_run_status       text CHECK (last_run_status IN ('ok', 'failed')),
    last_run_error        text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by_user_id    uuid REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE backup_schedules_snapshot (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  text NOT NULL,
    interval_amount       int  NOT NULL CHECK (interval_amount > 0),
    interval_unit         text NOT NULL CHECK (interval_unit IN ('minutes', 'hours')),
    remote_connection_id  uuid REFERENCES remote_backup_connections(id) ON DELETE SET NULL,
    retention_count       int  NOT NULL DEFAULT 24 CHECK (retention_count >= 1),
    enabled               boolean NOT NULL DEFAULT true,
    last_run_at           timestamptz,
    last_run_status       text CHECK (last_run_status IN ('ok', 'failed')),
    last_run_error        text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by_user_id    uuid REFERENCES users(id) ON DELETE SET NULL
);

-- Triggers updated_at (fonction set_updated_at() définie dans 001_init.sql)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_backup_schedules_full_updated_at') THEN
        CREATE TRIGGER trg_backup_schedules_full_updated_at
            BEFORE UPDATE ON backup_schedules_full
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_backup_schedules_snapshot_updated_at') THEN
        CREATE TRIGGER trg_backup_schedules_snapshot_updated_at
            BEFORE UPDATE ON backup_schedules_snapshot
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- Trace de quel schedule a déclenché un backup local (pour la rétention par schedule)
ALTER TABLE local_backups ADD COLUMN source_schedule_full_id     uuid REFERENCES backup_schedules_full(id)     ON DELETE SET NULL;
ALTER TABLE local_backups ADD COLUMN source_schedule_snapshot_id uuid REFERENCES backup_schedules_snapshot(id) ON DELETE SET NULL;
ALTER TABLE local_backups ADD CONSTRAINT local_backups_source_single CHECK (
    (source_schedule_full_id IS NULL) OR (source_schedule_snapshot_id IS NULL)
);

CREATE INDEX idx_local_backups_source_full     ON local_backups(source_schedule_full_id, created_at DESC)     WHERE source_schedule_full_id     IS NOT NULL;
CREATE INDEX idx_local_backups_source_snapshot ON local_backups(source_schedule_snapshot_id, created_at DESC) WHERE source_schedule_snapshot_id IS NOT NULL;
```

**Pourquoi 2 colonnes FK distinctes sur `local_backups`** : préserve les contraintes FK natives Postgres (CASCADE/SET NULL propres) au lieu d'une colonne polymorphique manuelle. Le CHECK `local_backups_source_single` garantit qu'au plus une est non-null. Les deux NULL = backup manuel.

**`retention_count` défauts** : 10 pour full (10 jours si schedule quotidien), 24 pour snapshot (24h si schedule horaire). Configurables par l'utilisateur.

## Architecture backend

### Dépendance Python

À ajouter dans `backend/pyproject.toml` :
- `apscheduler>=3.10,<4` — gère cron + interval triggers nativement, mode AsyncIOScheduler attaché au loop FastAPI.

Le Dockerfile fait déjà `uv pip install --system --no-cache .` depuis le pyproject (cf. leçon Harpocrate : pas de liste hardcodée chez nous).

### Services métier

**Nouveau** `backend/src/agflow/services/backup_schedules_service.py` (~250 lignes ; split en sous-modules si dépassement de la limite 300 du CLAUDE.md)

API publique :
```python
# Full
async def list_full_schedules() -> list[FullScheduleSummary]
async def get_full_schedule(id: UUID) -> FullScheduleSummary
async def create_full_schedule(payload: FullScheduleCreate, actor_user_id: UUID | None) -> FullScheduleSummary
async def update_full_schedule(id: UUID, payload: FullScheduleUpdate) -> FullScheduleSummary
async def delete_full_schedule(id: UUID) -> None
async def set_full_enabled(id: UUID, enabled: bool) -> FullScheduleSummary

# Snapshot (mêmes signatures, kind différent)
async def list_snapshot_schedules() -> list[SnapshotScheduleSummary]
async def get_snapshot_schedule(id: UUID) -> SnapshotScheduleSummary
async def create_snapshot_schedule(payload: SnapshotScheduleCreate, actor_user_id: UUID | None) -> SnapshotScheduleSummary
async def update_snapshot_schedule(id: UUID, payload: SnapshotScheduleUpdate) -> SnapshotScheduleSummary
async def delete_snapshot_schedule(id: UUID) -> None
async def set_snapshot_enabled(id: UUID, enabled: bool) -> SnapshotScheduleSummary

# Communs
async def record_run(*, schedule_id: UUID, kind: Literal['full','snapshot'], status: Literal['ok','failed'], error: str | None = None) -> None
async def prune_old_backups(*, schedule_id: UUID, kind: Literal['full','snapshot'], retention_count: int) -> int  # nb supprimés
```

**Validation cron** : `croniter(cron_expr)` au `create`/`update` (croniter est une transitive d'APScheduler). Si invalide → `ValueError` → 422.

**Exceptions exposées** :
- `ScheduleNotFoundError` → 404
- `InvalidCronExpressionError` → 422
- `InvalidIntervalError` → 422

### Job runner

**Nouveau** `backend/src/agflow/services/backup_job_runner.py` (~150 lignes)

```python
async def run_full_job(schedule_id: UUID) -> None
async def run_snapshot_job(schedule_id: UUID) -> None
```

Chaque fonction :

1. Lit le schedule depuis DB. Si `enabled=false` → no-op (sécurité concurrente : APScheduler peut avoir un tick en vol pendant qu'on a désactivé).
2. `local_backups_service.create_backup(source_schedule_*_id=schedule_id)` — utilise déjà `backup_lock` Postgres advisory interne.
3. Si `remote_connection_id` non-null :
   - `rbc_service.get_connection(...)` → si supprimé entre-temps → log warning + skip push (`record_run(status='ok', error=None)` quand même).
   - `rbc_service.fetch_credentials(...)` → `provider.upload_stream(remote_path, filename, source)`.
   - Si push échoue → `record_run(status='failed', error=...)` mais on garde le backup local. L'utilisateur peut le re-pousser manuellement plus tard via le bouton push existant.
4. `record_run(status='ok')` si tout OK.
5. `prune_old_backups(schedule_id, kind, retention_count)` → liste les `local_backups` de CE schedule triés par `created_at DESC`, garde les `retention_count` premiers, supprime fichier + row pour les autres.
6. Wrap tout dans try/except global : si erreur quelque part avant le push → `record_run(status='failed', error=...)` + propagation à APScheduler (qui logue son propre warning).

**`local_backups_service.create_backup`** modifié pour accepter `source_schedule_full_id` et `source_schedule_snapshot_id` optionnels (par défaut tous deux None = backup manuel). Pas de changement de signature pour les callers existants.

### Worker APScheduler

**Nouveau** `backend/src/agflow/services/backup_scheduler.py` (~120 lignes)

```python
_scheduler: AsyncIOScheduler | None = None
_db_sync_interval_s = 30  # tick re-sync DB → APScheduler

async def start() -> None              # appelé dans main.lifespan
async def stop() -> None
async def reload_schedules() -> None   # lit DB, diff avec jobs APScheduler, ADD/MODIFY/REMOVE
async def trigger_now(*, schedule_id: UUID, kind: Literal['full','snapshot']) -> None
```

**Stratégie de re-sync** : tick toutes les 30s. Diff par `(id, updated_at)` :
- Job présent en DB mais absent dans APScheduler → `add_job(id=str(schedule.id), ...)`
- Job présent dans les deux mais `updated_at` plus récent en DB → `modify_job(id, ...)`
- Job absent en DB mais présent dans APScheduler → `remove_job(id)`

**Pas de hot-reload immédiat à la création** dans la V1 (le job apparaît au prochain tick de re-sync, ≤30s). Acceptable pour MVP.

**`max_instances=1` par job** APScheduler → si un job précédent tourne encore quand le suivant ticke, APScheduler skip. Évite la concurrence sur un même schedule (ex: dump qui dure 2 min avec interval 1 min).

**`coalesce=True`** → si plusieurs ticks ratés (worker à l'arrêt), un seul rattrapage au démarrage.

**`trigger_now`** : utilise `scheduler.add_job(..., next_run_time=now())` avec un id unique éphémère, sans modifier le schedule régulier.

### API admin

**Nouveau** `backend/src/agflow/api/admin/backup_schedules.py` (~150 lignes)

Routes sous `/api/admin/backup-schedules` (require_admin) :

| Méthode | Path | Action | Codes erreur |
|---|---|---|---|
| GET | `/full` | liste schedules full | 401/403 |
| POST | `/full` | create full | 422 cron invalide, 404 remote_connection_id |
| PUT | `/full/{id}` | update full (cron, name, remote_id, retention, enabled) | 404, 422 |
| DELETE | `/full/{id}` | delete | 404 |
| POST | `/full/{id}/run-now` | trigger immédiat via APScheduler | 404 |
| POST | `/full/{id}/set-enabled` | toggle enabled (body `{enabled: bool}`) | 404 |
| GET | `/snapshot` | liste schedules snapshot | 401/403 |
| POST | `/snapshot` | create snapshot | 422 interval invalide, 404 remote_connection_id |
| PUT | `/snapshot/{id}` | update | 404, 422 |
| DELETE | `/snapshot/{id}` | delete | 404 |
| POST | `/snapshot/{id}/run-now` | trigger immédiat | 404 |
| POST | `/snapshot/{id}/set-enabled` | toggle enabled | 404 |

12 endpoints au total. `require_admin` global au router.

### Worker à supprimer

`backend/src/agflow/workers/remote_backup_pusher.py` → **supprimé**. Sa logique « 1 backup partagé + push toutes les connexions snapshots » est remplacée par les schedules explicites. Branchement dans `main.py:lifespan` retiré.

### main.py lifespan

Remplace l'import + démarrage du `remote_backup_pusher` par :
```python
from agflow.services.backup_scheduler import start as _backup_scheduler_start, stop as _backup_scheduler_stop
# ... dans lifespan :
await _backup_scheduler_start()
# ... yield ...
await _backup_scheduler_stop()
```

### local_backups_service modifications

**Modif** `local_backups_service.create_backup` : ajoute paramètres optionnels keyword-only :
```python
async def create_backup(
    *,
    created_by_user_id: UUID | None = None,
    source_schedule_full_id: UUID | None = None,
    source_schedule_snapshot_id: UUID | None = None,
) -> LocalBackupSummary
```
INSERT row avec les 2 colonnes supplémentaires.

**Modif** `_to_dto` (ou équivalent) : dérive `source_kind: Literal["manual","full","snapshot"]` :
- `source_schedule_full_id IS NOT NULL` → `"full"`
- `source_schedule_snapshot_id IS NOT NULL` → `"snapshot"`
- sinon → `"manual"`

**Modif** schema `LocalBackupSummary` (Pydantic) : ajoute `source_kind: Literal["manual","full","snapshot"]`.

## Architecture frontend

### API client

**Nouveau** `frontend/src/lib/backupSchedulesApi.ts` (~140 lignes)

```typescript
export type ScheduleKind = "full" | "snapshot";

export interface FullScheduleSummary {
  id: string;
  name: string;
  cron_expr: string;
  remote_connection_id: string | null;
  retention_count: number;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: "ok" | "failed" | null;
  last_run_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SnapshotScheduleSummary extends Omit<FullScheduleSummary, "cron_expr"> {
  interval_amount: number;
  interval_unit: "minutes" | "hours";
}

export interface CreateFullPayload {
  name: string;
  cron_expr: string;
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export interface CreateSnapshotPayload {
  name: string;
  interval_amount: number;
  interval_unit: "minutes" | "hours";
  remote_connection_id?: string | null;
  retention_count?: number;
  enabled?: boolean;
}

export const backupSchedulesApi = {
  listFull, createFull, updateFull, removeFull, runFullNow, setFullEnabled,
  listSnapshot, createSnapshot, updateSnapshot, removeSnapshot, runSnapshotNow, setSnapshotEnabled,
};
```

### Hook React Query

**Nouveau** `frontend/src/hooks/useBackupSchedules.ts` (~110 lignes)

```typescript
export function useFullSchedules()       // useQuery + mutations create/update/remove/runNow/setEnabled
export function useSnapshotSchedules()   // idem
```

Auto-refresh sur `last_run_at` toutes les 30s (`refetchInterval: 30_000`) pour voir les exécutions sans recharger la page.

### Page Backups — refonte

Modifier `frontend/src/pages/BackupsPage.tsx`. Structure cible :

```
┌── Page Backups ─────────────────────────────────────────────┐
│ [ Sauvegarde manuelle maintenant ]                          │
│                                                             │
│ ── Planifications complètes (cron) ────────── [+ Ajouter] ──│
│ Nom         | Cron       | Remote        | Rétention | … │
│ db-jour     | 0 3 * * *  | s3-prod       | 10        | …  │
│ db-hebdo    | 0 3 * * 0  | s3-prod       | 4         | …  │
│                                                             │
│ ── Snapshots (interval) ──────────────── [+ Ajouter] ──────│
│ Nom         | Interval   | Remote        | Rétention | … │
│ rapide      | 15 min     | (aucun)       | 24        | …  │
│ horaire     | 1 h        | gdrive-perso  | 48        | …  │
│                                                             │
│ ── Sauvegardes locales ──────────────────────────────────── │
│ Filtre : [ Toutes ▾ Manuelles ▾ Pleines ▾ Snapshots ▾ ]   │
│ (Liste existante : filename, source, status, push, restore) │
└─────────────────────────────────────────────────────────────┘
```

Colonnes communes des tables schedules :
- Nom
- Cron (full) ou Interval avec format human (`15 min`, `1 h`) (snapshot)
- Remote : nom de la connexion ou « (aucun) »
- Rétention (count)
- Dernier run : timestamp relatif + badge statut (✓ vert / ✗ rouge avec tooltip erreur tronquée)
- Actions :
  - Toggle enabled (`<input type="checkbox">` stylé — cohérent avec le pattern `HarpocrateVaultsTab` puisqu'on n'a pas de `Switch` shadcn)
  - Bouton « Run now » (icône play)
  - Bouton edit (icône pencil)
  - Bouton delete (icône trash, avec ConfirmDialog)

### Composants

- **Nouveau** `frontend/src/components/backups/FullSchedulesSection.tsx` (~180 lignes) — tableau + dialog create/edit
- **Nouveau** `frontend/src/components/backups/SnapshotSchedulesSection.tsx` (~180 lignes) — idem
- **Nouveau** `frontend/src/components/backups/BackupNowButton.tsx` (~50 lignes) — bouton manuel global qui appelle `POST /api/admin/local-backups` existant
- **Modif** `frontend/src/components/backups/LocalBackupsSection.tsx` — ajout filtre source : `all | manual | full | snapshot` (filtrage client sur le champ `source_kind` exposé par le backend)

### Dialog create/edit

**Form full** :
- Nom (input)
- Expression cron (input + presets : « Tous les jours 3h » `0 3 * * *`, « Toutes les heures » `0 * * * *`, « Tous les lundis 3h » `0 3 * * 1`)
- Connexion remote (select des `remote_backup_connections` + option « Aucune »)
- Rétention (input number, défaut 10, min 1)
- Activé (checkbox, défaut true)

**Form snapshot** :
- Nom
- Intervalle : input number + select unité (Minutes / Heures)
- Connexion remote (select)
- Rétention (input number, défaut 24, min 1)
- Activé (checkbox)

Validation Zod : `cron_expr` via regex basique (5 ou 6 champs séparés par espace — la vraie validation reste côté backend via croniter), `interval_amount > 0`.

### i18n

**~40 nouvelles clés FR + EN** sous `backups.schedules.*` :

- `fullTitle`, `snapshotTitle`, `addFull`, `addSnapshot`, `noneConfigured`
- `colName`, `colCron`, `colInterval`, `colRemote`, `colRetention`, `colLastRun`, `colActions`
- `cronPresets.daily3am`, `cronPresets.hourly`, `cronPresets.mondays`
- `runNow`, `runNowSuccess`, `runNowError`, `runNowRunning`
- `toggleEnabled`, `enabled`, `disabled`
- `formCronLabel`, `formCronHint`, `formIntervalLabel`, `formIntervalAmount`, `formIntervalUnit`, `formRetentionLabel`, `formRetentionHint`, `formRemoteOptional`, `formRemoteNone`
- `lastRunOk`, `lastRunFailed`, `lastRunNever`
- `deleteConfirmTitle`, `deleteConfirmDescription`
- `backupNowButton`, `backupNowSuccess`, `backupNowError`
- `filterSource`, `filterAll`, `filterManual`, `filterFull`, `filterSnapshot`

## Documentation

**Pas de nouveau guide admin** : la fonctionnalité est self-explanatory via les libellés UI et les presets cron. Si besoin futur d'aide cron (« je veux toutes les heures sauf la nuit »), ajouter un tooltip helper plus tard.

## Tests

### Backend (~35 nouveaux)

| Fichier | Tests | Type |
|---|---|---|
| `tests/services/test_backup_schedules_service.py` | CRUD full + snapshot, validation cron (croniter), validation interval > 0, enabled toggle, record_run + last_run_* update, prune_old_backups (delete row + fichier) | integration DB (fresh_db) |
| `tests/services/test_backup_job_runner.py` | run_full_job happy path (create_backup + push remote + prune) / no remote (juste local) / remote KO (status=failed mais backup local préservé) / lock backup_lock empêche overlap | integration DB + mocks providers |
| `tests/services/test_backup_scheduler.py` | start/stop scheduler, reload_schedules diff DB↔APScheduler (ADD/MODIFY/REMOVE), trigger_now appelle bien run_*_job | unit (mock AsyncIOScheduler) |
| `tests/api/test_admin_backup_schedules.py` | 12 endpoints : auth, viewer 403, payloads valides/invalides, run-now, set-enabled, 404, validation cron invalide → 422 | integration HTTP |
| `tests/services/test_local_backups_source_kind.py` | _to_dto dérive `source_kind` correctement selon les 3 cas (manual / full / snapshot) | unit |

### Frontend

Vitest sur `useBackupSchedules.ts` (mocks api client) et validations Zod du form (cron regex, interval > 0).

### Validation E2E

`./scripts/run-test.sh` — la suite pytest tourne dans le LXC fresh. Les ~35 nouveaux tests passent. Smoke métier manuel post-déploiement : créer un schedule snapshot interval 1 min via UI, attendre 60s, vérifier qu'un backup apparaît dans la liste avec source `snapshot` et que la connexion remote (si configurée) a reçu le fichier.

## Scope V1

### Livré
- ✅ 2 tables schedules (full cron + snapshot interval)
- ✅ Worker APScheduler (tick 30s pour re-sync DB)
- ✅ Job runner (create backup + push remote optionnel + record last_run)
- ✅ Rétention par schedule (delete row + fichier au-delà de `retention_count`)
- ✅ 12 endpoints API admin (CRUD + run-now + set-enabled, séparés full/snapshot)
- ✅ Page Backups refondue : section schedules full + snapshot + bouton « Sauvegarde manuelle » + filtre source sur la liste
- ✅ i18n FR/EN (~40 clés)
- ✅ Suppression du `remote_backup_pusher` (remplacé)

### Out-of-scope V1 (différé)
- ❌ Hot-reload immédiat du scheduler à la création/edit (latence ≤ 30s acceptée)
- ❌ Historique d'exécutions détaillé (juste `last_run_*` sur le schedule, pas d'archive)
- ❌ Notifications sur échec (email/webhook)
- ❌ Schedules cross-instance (suppose 1 seul backend actif — c'est notre cas, single-replica)
- ❌ Pause programmée (« arrêter le schedule du 1er au 15 août »)
- ❌ Diff incrémental / WAL streaming (toujours full dump)
- ❌ Rotation par durée (`retention_days`) — uniquement par count

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| APScheduler + asyncpg : conflit event loop ? | AsyncIOScheduler s'attache au loop FastAPI ; testé via le pattern lifespan (start/stop). Si problème, fallback BackgroundScheduler avec wrapper async. |
| Overlap de jobs (dump > interval) | `max_instances=1` par job APScheduler → skip si en cours. Le `backup_lock` advisory PG ajoute une 2e sécurité au cas où plusieurs replicas (futur). |
| Suppression d'une `remote_backup_connection` référencée | FK `ON DELETE SET NULL` → le schedule survit mais ne pushe plus. UI affiche « Remote: (supprimée) » + warning. Logué quand le job tourne sans push. |
| Suppression d'un schedule alors qu'un job tourne | APScheduler `remove_job(jobid)` n'interrompt pas le job en cours, juste le déplanifie. Le job en cours finit normalement. Rétention/prune utilise toujours le `source_schedule_*_id` du backup (orphelin si schedule supprimé ensuite — pas un drame). |
| Rétention par count vs upload remote en retard | La rétention compte UNIQUEMENT les backups locaux du schedule. On ne supprime PAS sur le remote (l'utilisateur gère la rétention remote via lifecycle policy S3/etc.). Documenté côté UI dans un tooltip. |
| Cron invalide saisi par admin | Validation `croniter(expr)` au create/update → 422 explicite avec message. Côté UI : validation Zod basique + try-catch sur l'erreur backend. |
| Saturation disque local | `retention_count` borne. Mais si l'utilisateur règle à 1000, c'est sa responsabilité. Logué le total taille au sein du job. |
| `apscheduler` ne supporte pas Python 3.12 ? | apscheduler 3.10+ supporte Python 3.8-3.13. OK. |
| Cron syntax variants (5 vs 6 champs avec seconds) | `croniter` accepte les 5 champs standards (minute heure jour mois jour-semaine). On documente : pas de support des secondes. |

## Effort estimé

~15-18 commits, **2.5-3 jours wall time** :

- **Jour 1** : migrations + service schedules + tests CRUD + croniter validation
- **Jour 2** : job_runner + backup_scheduler APScheduler + remplacement worker + tests integration + suppression `remote_backup_pusher`
- **Jour 3** : 12 endpoints API + tests HTTP + frontend (api client, hook, 3 composants, filtre source, i18n) + validation E2E `run-test.sh`

## Conventions de commit

- `feat(backups-db):` — migration 109
- `feat(backups-schedules):` — service + tests CRUD
- `feat(backups-scheduler):` — APScheduler worker, job_runner, remplacement remote_backup_pusher
- `feat(backups-api):` — 12 endpoints admin
- `feat(backups-ui):` — frontend (lib, hook, composants, i18n)
- `chore(backups):` — apscheduler dep
- `docs(backups):` — si besoin (probablement pas pour V1)

## Prochaine étape

Plan d'implémentation TDD détaillé via la skill `superpowers:writing-plans`, qui découpera ces 15-18 commits en tâches red/green/refactor exécutables une par une.
