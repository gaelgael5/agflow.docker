# Backup schedules multi-remote + wizard — Design

**Date** : 2026-05-20
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Étendre le système `backup_schedules_full` (cron pg_dump) :

1. **Multi-remote** : une planif peut pousser le même backup vers **N** remotes au lieu d'un seul.
2. **Push history par remote** : chaque push (par couple `local_backup × remote`) est traçé en DB avec son statut. Re-push manuel possible.
3. **Wizard de création** 3 étapes (récurrence → moment → destinations) qui masque la complexité du cron.
4. **Option `keep_local`** : flag explicite « conserver une copie locale ». Si décoché, le fichier est supprimé après pushes réussis. La row `local_backups` reste pour l'audit.

Le système `backup_schedules_snapshot` ayant été retiré (migration 112), seul `backup_schedules_full` est concerné.

## Contexte

### Ce qui existe (audit)

- DB : `backup_schedules_full.remote_connection_id` (FK unique, nullable, `ON DELETE SET NULL`)
- Service : `backup_job_runner.py` lit `schedule.remote_connection_id` et push à 1 remote
- UI : `FullSchedulesSection.tsx` form avec `destination: "local" | "remote"` + `remote_connection_id` unique
- Pattern de référence : PITR (`pitr_config_remotes` + `pitr_basebackup_pushes`)

### Ce qui manque

- N remotes par planif
- Suivi de l'état de chaque push
- Re-push manuel
- UX simplifiée pour la cadence (cron exposé brut aujourd'hui)

## Décisions structurantes (figées en brainstorming)

| # | Axe | Décision | Rationale |
|---|---|---|---|
| 1 | Push history | **Table `local_backup_pushes`** (status par remote) | Cohérent avec `pitr_basebackup_pushes`. Permet re-push individuel. |
| 2 | Migration data | **Migrer + DROP COLUMN** `remote_connection_id` | Préserve l'existant, pas de double source. |
| 3 | Validation | **≥ 1 destination** (refusé sinon) | Évite les planifs orphelines. |
| 4 | Stockage cadence | **`cron_expr`** (le wizard compose et parse) | Pas de migration sur le champ, compatible avec l'existant. |
| 5 | Approche UI | **Wizard stepper** 3 phases (Next/Back) | Colle exactement à la demande utilisateur. |
| 6 | `keep_local=false` semantique | **Fichier supprimé seulement si tous pushes 'ok'** | Sécurité : on conserve une copie en cas d'échec partiel. |

## Architecture d'ensemble

```
┌── Page Backups ────────────────────────────────────────────────────┐
│ [+ Ajouter planification]  ← ouvre <ScheduleWizard />              │
│                                                                    │
│ ── Sauvegardes complètes (cron pg_dump) ──────────────────────────│
│  Nom         | Récurrence            | Destinations           |   │
│  db-quotidien| Tous les jours à 3h   │ ✓ local · s3-prod ·   │   │
│              │                       │ gdrive                 │⋯  │
│  db-horaire  | Toutes les heures :15 │ s3-prod · ftps-bkp     │⋯  │
│                                                                    │
│ ── Sauvegardes locales ──────────────────────────────────────────│
│  filename.dump | 1.2 GB | source: db-quotidien                 │  │
│                          Pushes: ✓ s3-prod  ✗ gdrive  ⏳ ftps  │⋯ │
└────────────────────────────────────────────────────────────────────┘

ScheduleWizard (modal Dialog) :

Step 1/3 — Récurrence       Step 2/3 — Moment              Step 3/3 — Destinations
 ◯ Toutes les heures         (si hourly) À la min : [15]    Nom : [db-quotidien      ]
 ◯ Tous les jours            (si daily)  À l'heure : [03]   ☑ Conserver local
                                                            ☐ s3-prod
                                                            ☐ gdrive
                                                            Rétention : [10]
        [Suivant]                  [← Précédent  Suivant]      [← Précédent  Enregistrer]

         ↓ POST /api/admin/backup-schedules/full
         { name, cron_expr: "15 * * * *", remote_connection_ids: [...], keep_local, retention_count }

┌── Backend ─────────────────────────────────────────────────────────┐
│  api/admin/backup_schedules.py  (MODIFIÉ : multi-remote payloads)  │
│  api/admin/local_backups.py     (MODIFIÉ : + 2 endpoints pushes)   │
│                                                                    │
│  services/backup_schedules_service.py (MODIFIÉ : signatures)       │
│  services/backup_job_runner.py        (MODIFIÉ : boucle pushes)    │
│  services/local_backup_pushes_service.py (NEW : push history)      │
│  services/local_backups_service.py    (MODIFIÉ : delete_file_only) │
└────────────────────────────────────────────────────────────────────┘

         ▼ SQL / Provider upload

┌── Postgres ─────────────────────────────┐  ┌── Remote storage providers ────────┐
│ backup_schedules_full                   │  │ S3, GDrive, FTPS, SFTP             │
│ backup_schedule_full_remotes (join)     │  │ via remote_backup_providers/       │
│ local_backups (+ local_file_present)    │  │ factory.get_provider(kind, ...)    │
│ local_backup_pushes                     │  │ provider.upload_stream(path, ...)  │
└─────────────────────────────────────────┘  └────────────────────────────────────┘
```

**Composants ajoutés** :
- Migration 114 (2 nouvelles tables + 2 nouvelles colonnes + migration data + drop col)
- `local_backup_pushes_service.py` (~150 LoC)
- 2 endpoints REST (GET pushes, POST re-push)
- `ScheduleWizard.tsx` (~280 LoC) + `formatCronHuman` + `parseCron`
- ~30 clés i18n FR/EN

**Composants modifiés** :
- `backup_schedules_service.py` : signatures `remote_connection_ids: list[UUID]` + `keep_local: bool`
- `backup_job_runner.py` : INSERT pushes pending + loop push + delete file si keep_local=false
- `local_backups_service.py` : `delete_file_only` (préserve la row)
- `FullSchedulesSection.tsx` : utilise le wizard
- `LocalBackupsSection.tsx` : colonne pushes + menu re-push
- API client TS + hooks adaptés

**Composants retirés** :
- Le form mono-page actuel d'ajout d'une planif (remplacé par le wizard)
- La logique mono-`remote_connection_id` côté API et UI

## Modèle de données

### Migration 114 — `backend/migrations/114_backup_schedules_multi_remote.sql`

```sql
-- 114_backup_schedules_multi_remote.sql
-- Multi-remote pour backup_schedules_full + push history par remote

-- 1) Join table config : N remotes par schedule
CREATE TABLE backup_schedule_full_remotes (
    schedule_id          uuid NOT NULL REFERENCES backup_schedules_full(id) ON DELETE CASCADE,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (schedule_id, remote_connection_id)
);

CREATE INDEX idx_backup_schedule_full_remotes_remote
    ON backup_schedule_full_remotes (remote_connection_id);

-- 2) Push history par (local_backup, remote)
CREATE TABLE local_backup_pushes (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    local_backup_id      uuid NOT NULL REFERENCES local_backups(id) ON DELETE RESTRICT,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE RESTRICT,
    status               text NOT NULL CHECK (status IN ('pending', 'pushing', 'ok', 'failed')),
    pushed_at            timestamptz,
    error                text,
    remote_path          text,
    size_bytes           bigint,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (local_backup_id, remote_connection_id)
);

CREATE INDEX idx_local_backup_pushes_local
    ON local_backup_pushes (local_backup_id);
CREATE INDEX idx_local_backup_pushes_remote
    ON local_backup_pushes (remote_connection_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_local_backup_pushes_updated_at') THEN
        CREATE TRIGGER trg_local_backup_pushes_updated_at
            BEFORE UPDATE ON local_backup_pushes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- 3) Flag "garder local" sur le schedule
ALTER TABLE backup_schedules_full
    ADD COLUMN keep_local boolean NOT NULL DEFAULT true;

-- 4) Flag sur local_backups : fichier encore présent localement ou pas
ALTER TABLE local_backups
    ADD COLUMN local_file_present boolean NOT NULL DEFAULT true;

-- 5) Migrer les remote_connection_id existants vers la join table
INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id)
SELECT id, remote_connection_id
FROM backup_schedules_full
WHERE remote_connection_id IS NOT NULL;

-- 6) Dropper la colonne mono-remote (sa valeur est désormais dans la join table)
ALTER TABLE backup_schedules_full DROP COLUMN remote_connection_id;
```

### Notes de design

- **FK `ON DELETE RESTRICT`** sur `local_backup_pushes` (vs CASCADE pour `backup_schedule_full_remotes`) : préserve l'audit en cas de suppression d'un local_backup ou d'une remote. L'admin doit explicitement nettoyer les pushes avant de supprimer.
- **UNIQUE `(local_backup_id, remote_connection_id)`** : pas de doublon ; le re-push manuel UPDATE la row existante.
- **`keep_local` défaut `true`** : préserve le comportement actuel.
- **`local_file_present` défaut `true`** : tous les backups existants ont leur fichier au moment de la migration. Passe à `false` quand `keep_local=false` + tous pushes 'ok'.
- **Migration data idempotent** : `INSERT ... WHERE remote_connection_id IS NOT NULL` skip les planifs sans remote (= local seul aujourd'hui) → elles restent telles quelles, `keep_local=true` par défaut + 0 remote = backup local seul.

## API REST

### Endpoints modifiés — `backend/src/agflow/api/admin/backup_schedules.py`

| Méthode | Path | Changement |
|---|---|---|
| GET | `/full` | Retourne `remote_connection_ids: list[UUID]` + `keep_local: bool` |
| GET | `/full/{id}` | Idem |
| POST | `/full` | Accepte `remote_connection_ids: list[UUID]` + `keep_local: bool` |
| PUT | `/full/{id}` | Idem |
| GET | `/full/{id}/history` | Inchangé |

### Endpoints ajoutés — `backend/src/agflow/api/admin/local_backups.py`

| Méthode | Path | Action | Codes |
|---|---|---|---|
| GET | `/api/admin/local-backups/{backup_id}/pushes` | Liste les pushes d'un backup | 401/403, 404 |
| POST | `/api/admin/local-backups/{backup_id}/push/{remote_id}` | Re-push manuel | 401/403, 404, 409 |

### Validation côté backend (POST/PUT `/full`)

- `keep_local=false` ET `remote_connection_ids=[]` → **422** « au moins une destination requise »
- `remote_connection_ids` contient un UUID inexistant → **404**
- `cron_expr` invalide via `croniter` → **422**

### Schémas Pydantic — `backend/src/agflow/schemas/backup_schedules.py` (modifié)

```python
class FullScheduleSummary(BaseModel):
    id: UUID
    name: str
    cron_expr: str
    remote_connection_ids: list[UUID]        # ← remplace remote_connection_id
    keep_local: bool                          # ← nouveau
    retention_count: int
    enabled: bool
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime


class CreateFullPayload(BaseModel):
    name: str
    cron_expr: str
    remote_connection_ids: list[UUID] = []
    keep_local: bool = True
    retention_count: int = 10
    enabled: bool = True


class UpdateFullPayload(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    remote_connection_ids: list[UUID] | None = None  # None = ne pas modifier
    keep_local: bool | None = None
    retention_count: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
```

### Schémas Pydantic — `backend/src/agflow/schemas/local_backup_pushes.py` (nouveau)

```python
class LocalBackupPushSummary(BaseModel):
    id: UUID
    local_backup_id: UUID
    remote_connection_id: UUID
    remote_connection_name: str
    status: Literal["pending", "pushing", "ok", "failed"]
    pushed_at: datetime | None
    error: str | None
    remote_path: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime
```

### Sémantique des 2 nouveaux endpoints

**GET `/local-backups/{id}/pushes`** : `list[LocalBackupPushSummary]`. Vide si aucune entrée (backup manuel ou planif sans remote configurée).

**POST `/local-backups/{id}/push/{remote_id}`** :
1. Vérifier `local_backup` existe + `local_file_present=true` → sinon **409** « fichier local indisponible »
2. Si row push existe avec `status='ok'` → idempotent retour 200 (no-op)
3. UPDATE 'pushing' → upload provider → UPDATE 'ok' / 'failed'
4. **202 Accepted** + l'état actuel

### Affichage des pushes dans GET `/local-backups`

L'endpoint existant `GET /local-backups` (liste des backups) est étendu pour retourner `pushes: list[LocalBackupPushSummary]` agrégé par backup (LEFT JOIN + json_agg + FILTER WHERE non null, pattern PITR).

## Services backend

### `backup_schedules_service.py` (modifié)

```python
async def create_full_schedule(
    *,
    name: str,
    cron_expr: str,
    remote_connection_ids: list[UUID],
    keep_local: bool,
    retention_count: int,
    enabled: bool,
    actor_user_id: UUID | None,
) -> FullScheduleSummary

async def update_full_schedule(
    id: UUID, *,
    name: str | None = None,
    cron_expr: str | None = None,
    remote_connection_ids: list[UUID] | None = None,
    keep_local: bool | None = None,
    retention_count: int | None = None,
    enabled: bool | None = None,
) -> FullScheduleSummary
```

**Exceptions** :
- `InvalidCronError(ValueError)` → 422 (existante)
- `RemoteNotFoundError(LookupError)` → 404 (existante ou à ajouter)
- `EmptyDestinationsError(ValueError)` → 422 (nouvelle)

**Flow `create_full_schedule`** :
1. Valider `cron_expr` via `croniter`
2. Valider chaque `remote_connection_id` existe
3. Valider `not (keep_local is False and remote_connection_ids == [])`
4. Transaction asyncpg :
   - INSERT row dans `backup_schedules_full`
   - INSERT N rows dans `backup_schedule_full_remotes`
5. Retourner via re-SELECT (LEFT JOIN + array_agg)

**Flow `update_full_schedule`** : SETs conditionnels + si `remote_connection_ids is not None` (même `[]`) → DELETE + INSERT en transaction.

**Flow `get_full_schedule(id)` / `list_full_schedules()`** :

```sql
SELECT s.*,
       coalesce(
         array_agg(r.remote_connection_id) FILTER (WHERE r.remote_connection_id IS NOT NULL),
         ARRAY[]::uuid[]
       ) AS remote_connection_ids
FROM backup_schedules_full s
LEFT JOIN backup_schedule_full_remotes r ON r.schedule_id = s.id
GROUP BY s.id
ORDER BY s.created_at DESC
```

### `backup_job_runner.py` (modifié)

```python
async def run_full_job(schedule_id: UUID) -> None:
    schedule = await backup_schedules_service.get_full_schedule(schedule_id)

    # 1) Création du backup local (mandatory — source pour les pushes)
    backup = await local_backups_service.create_backup(
        source_schedule_full_id=schedule_id,
    )

    # 2) Si planif a des remotes : INSERT N rows 'pending'
    if schedule.remote_connection_ids:
        await local_backup_pushes_service.seed_pushes(
            backup_id=backup.id,
            remote_ids=schedule.remote_connection_ids,
        )
        all_pushes_ok = await local_backup_pushes_service.push_all_pending(backup_id=backup.id)
    else:
        all_pushes_ok = True  # pas de remote = success trivial

    # 3) Si keep_local=false ET tous les pushes OK → supprimer le fichier local
    if not schedule.keep_local and all_pushes_ok:
        await local_backups_service.delete_file_only(backup.id)

    # 4) Record run + prune
    await backup_schedules_service.record_run(schedule_id=schedule_id, status='ok')
    await backup_schedules_service.prune_old_backups(schedule_id, schedule.retention_count)
```

**Notes** :
- Si push échoue → file conservé même si `keep_local=false` (sécurité)
- Si tous pushes échouent → `record_run('failed', error='all N pushes failed')`
- Si pushes partiels → `record_run('ok')`, l'admin voit ✗ dans l'UI sur le local_backup

### `local_backup_pushes_service.py` (nouveau, ~150 lignes)

```python
class PushNotFoundError(LookupError): ...
class LocalFileMissingError(RuntimeError): ...
class PushAlreadyOkError(RuntimeError): ...


async def seed_pushes(*, backup_id: UUID, remote_ids: list[UUID]) -> None
    """INSERT 1 row 'pending' par remote pour ce backup."""


async def list_pushes(backup_id: UUID) -> list[LocalBackupPushSummary]
    """Retourne les pushes du backup avec name de la remote joint."""


async def push_all_pending(*, backup_id: UUID) -> bool
    """Boucle séquentielle sur les pushes 'pending'. Erreur par-remote catchée.
    Retourne True si TOUS 'ok', False sinon."""


async def push_one(*, backup_id: UUID, remote_id: UUID) -> LocalBackupPushSummary
    """Re-push manuel. Vérifie local_file_present=true (sinon LocalFileMissingError).
    Idempotent si status='ok'."""


async def _push_to_remote(*, backup_id, remote_id, local_file_path) -> tuple[str, int]
    """Upload via provider.upload_stream. Retourne (remote_path, size_bytes)."""
```

### `local_backups_service.py` (modifications mineures)

Nouvelle fonction :

```python
async def delete_file_only(backup_id: UUID) -> None
    """Supprime le fichier .dump localement, UPDATE local_file_present=false.
    La row local_backups est PRÉSERVÉE (audit + push history)."""
```

Modif de `prune_old_backups` : ne supprime pas les rows dont `local_file_present=false` (déjà sans fichier).

## Frontend

### Composant `ScheduleWizard.tsx` (~280 lignes)

Modal Dialog shadcn avec 3 steps. État local :

```typescript
interface WizardState {
  step: 1 | 2 | 3;
  recurrence: "hourly" | "daily" | null;
  offset: number | null;            // 0-59 si hourly, 0-23 si daily
  name: string;
  keepLocal: boolean;
  remoteConnectionIds: string[];
  retentionCount: number;
}
```

**Transitions** :
- Step 1 → 2 si `recurrence !== null`
- Step 2 → 3 si `offset !== null` et dans la plage valide
- Step 3 → Enregistrer si `name.length > 0` ET (`keepLocal === true` OU `remoteConnectionIds.length > 0`)

### Cron generation / parsing (côté client)

```typescript
function buildCron(recurrence: "hourly" | "daily", offset: number): string {
  if (recurrence === "hourly") return `${offset} * * * *`;
  return `0 ${offset} * * *`;
}

function parseCron(cron: string): { recurrence: "hourly" | "daily"; offset: number } | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [min, hr, dom, mon, dow] = parts;
  if (hr === "*" && dom === "*" && mon === "*" && dow === "*" && /^\d+$/.test(min)) {
    return { recurrence: "hourly", offset: parseInt(min, 10) };
  }
  if (min === "0" && dom === "*" && mon === "*" && dow === "*" && /^\d+$/.test(hr)) {
    return { recurrence: "daily", offset: parseInt(hr, 10) };
  }
  return null; // cron complexe non représentable
}
```

**Fallback à l'édition** : si `parseCron` retourne null, affichage « Cron personnalisé : `<expr>` » + bouton « Éditer en cron brut » qui ouvre un input simple.

### Modifications `FullSchedulesSection.tsx`

- Bouton « + Ajouter » → ouvre `<ScheduleWizard mode="create" />`
- Bouton « Édition » → `<ScheduleWizard mode="edit" initialSchedule={s} />` (pré-remplit via `parseCron`)
- Colonne « Récurrence » : `formatCronHuman(cron_expr)` → « Tous les jours à 03:00 » / « Toutes les heures à xx:15 »
- Colonne « Destination » : `✓ local` + `· s3-prod · gdrive` (badges remotes) ou `(local seul)` si pas de remote

### Modifications `LocalBackupsSection.tsx`

Nouvelle colonne **Pushes** affiche les badges par remote :

```
✓ s3-prod   ✗ gdrive   ⏳ ftps-bkp
```

Menu kebab par push échoué :
```
⋯ → Re-push vers gdrive
```

Si `local_file_present=false` : icône grisée + bouton « Télécharger » disabled.

### API client TS — modifications

`frontend/src/lib/backupSchedulesApi.ts` :
- `FullScheduleSummary.remote_connection_id` → `remote_connection_ids: string[]` + `keep_local: boolean`
- Payloads CreateFull / UpdateFull idem

`frontend/src/lib/backupsApi.ts` :
- `LocalBackup.pushes: LocalBackupPush[]` ← nouveau champ
- Nouvelles fonctions : `listPushes(backup_id)`, `pushBackup(backup_id, remote_id)`

### i18n — ~30 clés sous `backups.wizard.*` et `backups.pushes.*`

(Listées en détail dans la section frontend du brainstorm — exemples : `wizard.step1.hourly`, `wizard.step3.errorNoDestination`, `pushes.rePushAction`, etc.)

## Tests

### Backend (~30 nouveaux + ~10 adaptés)

| Fichier | Tests |
|---|---|
| `tests/db/test_migration_114_multi_remote.py` (nouveau) | Tables créées, colonnes ajoutées, migration data |
| `tests/services/test_backup_schedules_service.py` (adapté) | Signatures multi-remote, `EmptyDestinationsError`, validation remote_id, update remplace liste |
| `tests/services/test_local_backup_pushes_service.py` (nouveau) | `seed_pushes`, `push_all_pending` happy + partial, `push_one` idempotent, file missing → error |
| `tests/services/test_backup_job_runner.py` (adapté) | Multi-remote happy, push partiel, `keep_local=false` + ok → file supprimé, `keep_local=false` + fail → file conservé |
| `tests/api/test_admin_backup_schedules.py` (adapté) | POST/PUT `remote_connection_ids: list[UUID]`, 422 si 0 dest, 404 si remote inconnu |
| `tests/api/test_admin_local_backups.py` (adapté) | GET liste avec `pushes`, GET `/pushes`, POST re-push happy + 409 file absent + 409 déjà ok |

### Frontend (~12 tests Vitest)

- `ScheduleWizard.test.tsx` : navigation step 1→2→3, Précédent, validation 0 destination, mode edit pré-remplissage, cron complexe → fallback
- `formatCronHuman.test.ts` : `0 3 * * *` → "Tous les jours à 03:00", `15 * * * *` → "Toutes les heures à xx:15"
- `parseCron.test.ts` : 2 patterns + null pour cron complexe
- `LocalBackupsSection.test.tsx` : badges pushes + menu re-push appelé

### E2E

Pas d'extension de `run-test.sh` requise. Validation manuelle après deploy :
1. Créer planif via wizard → step 1 (par heure) → step 2 (minute 15) → step 3 (2 remotes + local) → Enregistrer
2. Vérifier DB : `cron_expr='15 * * * *'`, `keep_local=true`, 2 rows dans la join
3. Attendre déclenchement APScheduler
4. Vérifier `local_backup_pushes` : 2 rows 'ok'
5. UI : badges affichés sur le local_backup

## Découpage en 5 phases

| Phase | Périmètre | Effort |
|---|---|---|
| **P1 — DB + service backend** | Migration 114 + adaptation `backup_schedules_service` + `local_backup_pushes_service.py` (nouveau) + tests | 2-3j |
| **P2 — Job runner + API** | Refactor `backup_job_runner` + 2 nouveaux endpoints + adaptation existants + tests | 1-2j |
| **P3 — Wizard frontend** | `ScheduleWizard.tsx` + `formatCronHuman` + `parseCron` + intégration `FullSchedulesSection` + tests Vitest | 2-3j |
| **P4 — UI pushes** | Colonne pushes dans `LocalBackupsSection` + menu re-push + bouton edit utilise wizard + i18n FR/EN | 1-2j |
| **P5 — Validation** | Smoke manuel post-deploy machine 303 | 0.5j |

**Total : 6.5-10.5 jours wall** (~1.5-2 semaines).

## Risques résiduels

| Risque | Mitigation |
|---|---|
| Migration data échoue (remote orpheline) | `WHERE remote_connection_id IS NOT NULL` skip ce cas, pas de perte |
| Push partiel masqué dans last_run | UI signale via badges ✗ par push |
| `keep_local=false` + tous OK → file deleted | By-design, audit préservé via row |
| Renommer une remote | UI affiche le nouveau name (via JOIN) |
| Wizard ne parse pas cron complexe | Fallback « cron personnalisé » + édition brute |
| 2 admins éditent simultanément | Last-write-wins (acceptable V1) |
| Job en cours quand admin modifie | Le job a déjà lu sa snapshot — modif s'applique au run suivant |

## Critères d'acceptation V1

- [ ] Migration 114 appliquée, join table créée, data existante préservée
- [ ] POST `/full` accepte `remote_connection_ids: list[UUID]` + `keep_local: bool` → 422 si 0 destination
- [ ] `local_backup_pushes` rempli après chaque run, 1 row par remote
- [ ] POST `/local-backups/{id}/push/{remote_id}` permet de re-pousser un push échoué
- [ ] `keep_local=false` + tous pushes OK → fichier supprimé, `local_file_present=false`, row préservée
- [ ] Wizard 3 steps fonctionne (création + édition pré-remplie)
- [ ] Badges pushes affichés dans `LocalBackupsSection`
- [ ] Validation runtime sur LXC : créer via wizard, exécuter, vérifier pushes en DB + UI

## Out-of-scope V1 (différé V2)

- ❌ Récurrence "toutes les X heures" (sub-cron complexe)
- ❌ Récurrence hebdomadaire (chaque lundi à 3h, …)
- ❌ Optimistic locking sur éditions concurrentes
- ❌ Pause/reprise individuelle d'une remote
- ❌ Détection de coffre/remote supprimé + alerte UI
- ❌ Audit log historique des modifications de planif

## Conventions de commit

- `feat(backup-db):` — migration 114
- `feat(backup-services):` — services modifiés + pushes_service
- `feat(backup-api):` — endpoints REST adaptés + nouveaux
- `feat(backup-ui):` — wizard + colonne pushes
- `chore(backup):` — i18n + cleanup mono-remote
- `test(backup):` — tests dédiés
- `docs(backup):` — spec + plan

## Prochaine étape

Plan d'implémentation TDD détaillé via la skill `superpowers:writing-plans`, qui découpera les 5 phases en tâches red/green/refactor exécutables une par une.
