# Intégration métier du SDK Git Sync

**Date** : 2026-05-17
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Brancher le SDK Git Sync (`backend/sdk/git_sync/`, déjà livré et testé) dans le métier d'agflow.docker afin de permettre à l'admin :

- de **configurer** un repo Git distant (URL + auth + branche + auteur de commit + sélection de tables) ;
- d'**exporter** à la demande l'état courant de la base vers ce repo (CSV + dependencies.json + commit) ;
- d'**importer** depuis ce repo l'état d'une autre instance (preview + merge + delete orphans) ;
- de **planifier** un export récurrent via cron (même pattern qu'`backup_schedules`) ;
- de **consulter** l'historique des commits via l'API GitHub avec redirection vers la page commit GitHub au clic.

Le SDK est générique. L'intégration métier décide : où vit la config, comment elle est exposée, qui déclenche les actions, et comment l'UI reflète l'état du système.

## Contexte

L'app a actuellement :
- Un SDK Git Sync complet sous `backend/sdk/git_sync/` (1506 lignes, 73 tests verts) qui expose `ExportService`, `ImportService`, `GitService`, `DependencyResolver`, `VaultResolver`, `GitAuthProvider`. Voir spec SDK : `specs/sdk_git_sync_specs.md`.
- Un coffre Harpocrate par défaut (configuré via la page `/settings` onglet « Harpocrate »).
- Un pattern éprouvé de planification cron avec APScheduler (`backup_scheduler.py` + tables `backup_schedules_*`).
- Aucune table DB, aucun service métier, aucun endpoint, aucune UI pour Git Sync.

Le SDK attend en entrée un objet `GitConfig` Python (repo_url, auth_mode, auth_secret_ref, branch, etc.). Cet objet doit être **persistant** côté agflow (l'admin le configure une fois, le scheduler le relit à chaque tick).

## Décisions structurantes (tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Multi-config vs singleton | **Singleton** (1 seule config Git pour l'instance) | Une instance agflow synchronise avec UN repo. Multi-config complexifierait l'UI et n'a pas de cas d'usage identifié. Implémenté via `CHECK (id = 1)`. |
| 2 | Sélection des tables | **Free-form** : multi-select sur toutes les tables `public.*` | L'admin assume sa responsabilité (cas légitime : exporter `infra_*` mais pas `users`). Pas de blacklist hardcodée — warning UI en cas de table sensible visible (mais aucun blocage). |
| 3 | Planification | **Cron schedule** (pattern `backup_schedules`) + bouton « Run now » manuel | Permet automatisation (sync nocturne) et test (déclenchement immédiat sans attendre). Le cron tourne dans un AsyncIOScheduler séparé de celui des backups (concerns séparés). |
| 4 | Structure UI | **Onglet « Git Sync » dans la page `/settings`** existante (aux côtés de « Harpocrate ») | Le settings page est le bon endroit pour la config infra. Pas de page dédiée → cohérence avec Harpocrate. |
| 5 | Historique des syncs | **Pas de table de log**. Champs `last_*` sur la ligne singleton (cache UI) + appel API GitHub pour la liste des commits (clic = ouverture page commit GitHub) | Le repo Git EST l'historique. Doublonner serait gaspillage. Pour GitLab/Bitbucket : juste le lien externe sans liste enrichie (warning unsupported_host côté UI). |

## Modèle de données

### Migration 110 — `backend/migrations/110_git_sync_config.sql`

```sql
-- 110_git_sync_config.sql — Configuration singleton de la synchronisation Git

CREATE TABLE git_sync_config (
    id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton
    repo_url                  text NOT NULL,
    auth_mode                 text NOT NULL CHECK (auth_mode IN ('ssh_key', 'pat_https', 'basic_https')),
    auth_secret_ref           text NOT NULL,                    -- ex: 'agflow_default/git/agflow-sync'
    branch                    text NOT NULL DEFAULT 'main',
    commit_author_name        text NOT NULL DEFAULT 'agflow bot',
    commit_author_email       text NOT NULL DEFAULT 'bot@agflow.local',
    excluded_columns          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- { "users": ["password_hash", "token"] }
    selected_tables           jsonb NOT NULL DEFAULT '[]'::jsonb,   -- ["infra_categories", "infra_named_types"]
    cron_expr                 text,                                  -- ex: '0 4 * * *' (nullable = pas de cron)
    cron_enabled              boolean NOT NULL DEFAULT false,
    last_export_at            timestamptz,
    last_export_status        text CHECK (last_export_status IN ('ok', 'failed')),
    last_export_sha           text,
    last_export_error         text,
    last_export_tables_count  int,
    last_import_at            timestamptz,
    last_import_status        text CHECK (last_import_status IN ('ok', 'failed')),
    last_import_error         text,
    last_import_rows_inserted int,
    last_import_rows_updated  int,
    last_import_rows_deleted  int,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

-- Trigger updated_at (fonction set_updated_at() définie dans 001_init.sql)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_git_sync_config_updated_at') THEN
        CREATE TRIGGER trg_git_sync_config_updated_at
            BEFORE UPDATE ON git_sync_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
```

**Notes** :
- Le singleton est garanti par `PRIMARY KEY DEFAULT 1 CHECK (id = 1)` : toute tentative d'INSERT d'une seconde ligne lève une `UniqueViolationError`.
- `auth_secret_ref` n'est PAS un secret — c'est un pointeur vers Harpocrate (`vault_name/path`). Le secret réel (clé SSH, PAT, password) vit dans Harpocrate.
- `excluded_columns` est un mapping `{table: [columns]}` passé tel quel à `ExportService.run()`.
- `selected_tables` est la liste blanche des tables à synchroniser. Si vide → erreur côté UI (la sélection est obligatoire).
- Les champs `last_*` sont un cache UI — ils permettent d'afficher l'état dernière exécution sans interroger Git.

## Backend

### Service `backend/src/agflow/services/git_sync_service.py` (~200 lignes)

Module qui wrappe le SDK et gère la config singleton.

```python
from __future__ import annotations

from typing import Any
from uuid import UUID
import json
import structlog

from agflow.db.pool import execute, fetch_one, fetch_all
from agflow.schemas.git_sync import GitSyncConfigDTO, GitSyncExportResult, GitSyncImportPreview, GitSyncImportResult
from agflow.sdk.git_sync import ExportService, ImportService, GitService, VaultResolver, GitConfig
from agflow.services import vault_client

_log = structlog.get_logger(__name__)


async def get_config() -> GitSyncConfigDTO | None:
    """Lit la ligne singleton. None si pas encore configurée."""

async def upsert_config(*, repo_url, auth_mode, auth_secret_ref, branch,
                       commit_author_name, commit_author_email,
                       excluded_columns, selected_tables,
                       cron_expr, cron_enabled) -> GitSyncConfigDTO:
    """INSERT … ON CONFLICT (id) DO UPDATE."""

async def delete_config() -> None:
    """DELETE de la ligne singleton (réinitialisation complète)."""

async def list_available_tables() -> list[str]:
    """Liste toutes les tables `public.*` (information_schema), triées."""

async def record_export_run(*, status, sha, error, tables_count) -> None:
    """UPDATE last_export_*."""

async def record_import_run(*, status, error, rows_inserted, rows_updated, rows_deleted) -> None:
    """UPDATE last_import_*."""

async def run_export(*, module_name: str = "docker") -> GitSyncExportResult:
    """1) lit config, 2) résout auth via Harpocrate, 3) build GitConfig SDK,
       4) appelle ExportService.run(), 5) record_export_run().
       Toute exception → record_export_run(status='failed', error=...) puis re-raise."""

async def run_preview(*, module_name: str = "docker") -> GitSyncImportPreview:
    """Idem run_export mais avec ImportService.preview() (pas d'écriture DB)."""

async def run_import(*, module_name: str = "docker") -> GitSyncImportResult:
    """Idem mais avec ImportService.run(). record_import_run()."""
```

**Conventions** :
- Pas de logique métier dans les endpoints API — toute la résolution Harpocrate + appel SDK est ici.
- Le module exporté est `"docker"` (hardcodé, voir spec SDK §2). Si l'app évolue vers plusieurs modules, ce paramètre deviendra configurable via la table.
- `record_*` est appelé dans `try/finally` pour garantir que le statut est persisté même en cas d'exception.

### Service `backend/src/agflow/services/git_sync_github_client.py` (~80 lignes)

Client HTTP minimal pour l'API GitHub (lecture commits uniquement).

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
import httpx
import structlog

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ParsedRepo:
    host: str          # 'github.com'
    owner: str         # 'gaelgael5'
    repo: str          # 'agflow-sync'


@dataclass(frozen=True)
class GitCommit:
    sha: str
    short_sha: str             # sha[:7]
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str              # https://github.com/owner/repo/commit/sha


class UnsupportedHostError(Exception):
    """Host autre que github.com — pas de listing de commits, juste le lien."""


def parse_repo_url(repo_url: str) -> ParsedRepo:
    """Parse 'git@github.com:owner/repo.git' ou 'https://github.com/owner/repo(.git)'."""


async def list_commits(
    *,
    repo_url: str,
    branch: str,
    limit: int = 30,
    auth_token: str | None = None,
) -> list[GitCommit]:
    """GET https://api.github.com/repos/{owner}/{repo}/commits?sha={branch}&per_page={limit}.
       auth_token optionnel (PAT) pour augmenter le rate limit.
       Lève UnsupportedHostError si host != github.com."""
```

**Conventions** :
- Aucun secret loggé. URL GitHub API loggée sans header `Authorization`.
- Si rate-limited (429) → exception remontée, UI affiche un toast.
- V1 : github.com uniquement. GitLab/Bitbucket → `UnsupportedHostError` → UI affiche juste le repo_url cliquable.

### Worker `backend/src/agflow/services/git_sync_scheduler.py` (~80 lignes)

Wrapper AsyncIOScheduler **séparé** de `backup_scheduler` (concerns isolés, pas de risque de fuite de jobs).

```python
from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from agflow.services import git_sync_service

_log = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def start() -> None:
    """Démarre le scheduler + job interne __resync__ (tick 30s) qui relit la config."""

async def stop() -> None:
    """shutdown(wait=True)."""

async def reload_schedule() -> None:
    """Appelé par le tick __resync__ ET par upsert_config().
       Lit get_config(). Si cron_enabled et cron_expr → add/update job 'export'.
       Sinon → remove job 'export'."""

async def trigger_now() -> None:
    """Ajoute un job DateTrigger(now) qui appelle run_export()."""

async def _run_export_job() -> None:
    """Wrapper qui catch toute exception (sinon APScheduler stoppe le job)."""
```

**Job IDs** : `"export"`, `"__resync__"`, `"trigger-now:<uuid>"`.
`max_instances=1`, `coalesce=True` (si retard, ne pas accumuler).

### Endpoints API admin — `backend/src/agflow/api/admin/git_sync.py` (~140 lignes)

```python
from fastapi import APIRouter, Depends, HTTPException
from agflow.auth.dependencies import require_admin
from agflow.schemas.git_sync import (
    GitSyncConfigDTO, GitSyncConfigUpsert, GitSyncExportResult,
    GitSyncImportPreview, GitSyncImportResult, GitSyncCommitDTO,
)
from agflow.services import git_sync_service, git_sync_scheduler, vault_client
from agflow.services.git_sync_github_client import list_commits, parse_repo_url, UnsupportedHostError

router = APIRouter(
    prefix="/api/admin/git-sync",
    tags=["admin", "git-sync"],
    dependencies=[Depends(require_admin)],
)
```

**9 endpoints** :

| Méthode | Path | Réponse | Description |
|---|---|---|---|
| GET | `/config` | `GitSyncConfigDTO \| null` | Lit la config singleton. |
| PUT | `/config` | `GitSyncConfigDTO` | Upsert (INSERT ou UPDATE selon l'existence). Valide `cron_expr` via `CronTrigger.from_crontab()`. Recharge le scheduler. |
| DELETE | `/config` | 204 | Supprime la config. Stop le job export. |
| GET | `/available-tables` | `list[str]` | Liste les tables `public.*`. |
| POST | `/test-secret-ref` | `{ ok: bool, error: str \| null }` | Body : `{ auth_secret_ref: str }`. Tente `vault_client.resolve_ref()` sur le vault par défaut. Pour le bouton « Tester la résolution Harpocrate » du dialog config — permet de valider la ref AVANT de sauvegarder. |
| POST | `/export` | `GitSyncExportResult` | Déclenche un export manuel **synchrone** (200 OK). V1 : pas de mode async. Le SDK est rapide pour les tailles attendues. |
| POST | `/preview-import` | `GitSyncImportPreview` | Wrappe `ImportService.preview()`. Aucune écriture. |
| POST | `/import` | `GitSyncImportResult` | Wrappe `ImportService.run()`. Synchrone. |
| GET | `/commits?limit=30` | `list[GitSyncCommitDTO]` | Liste les commits du repo configuré. 422 si `UnsupportedHostError`. |

**Errors mapping** :
- 404 si config absente et endpoint nécessite la config
- 422 si `cron_expr` invalide / `selected_tables` vide / `UnsupportedHostError`
- 502 si erreur SDK upstream (Git unreachable, Harpocrate KO)

### Schémas Pydantic — `backend/src/agflow/schemas/git_sync.py` (~120 lignes)

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from apscheduler.triggers.cron import CronTrigger


class GitSyncConfigDTO(BaseModel):
    repo_url: str
    auth_mode: Literal["ssh_key", "pat_https", "basic_https"]
    auth_secret_ref: str
    branch: str
    commit_author_name: str
    commit_author_email: str
    excluded_columns: dict[str, list[str]]
    selected_tables: list[str]
    cron_expr: str | None
    cron_enabled: bool
    last_export_at: datetime | None
    last_export_status: Literal["ok", "failed"] | None
    last_export_sha: str | None
    last_export_error: str | None
    last_export_tables_count: int | None
    last_import_at: datetime | None
    last_import_status: Literal["ok", "failed"] | None
    last_import_error: str | None
    last_import_rows_inserted: int | None
    last_import_rows_updated: int | None
    last_import_rows_deleted: int | None
    created_at: datetime
    updated_at: datetime


class GitSyncConfigUpsert(BaseModel):
    repo_url: str = Field(min_length=1)
    auth_mode: Literal["ssh_key", "pat_https", "basic_https"]
    auth_secret_ref: str = Field(min_length=1)
    branch: str = Field(min_length=1, default="main")
    commit_author_name: str = Field(min_length=1, default="agflow bot")
    commit_author_email: str = Field(min_length=1, default="bot@agflow.local")
    excluded_columns: dict[str, list[str]] = Field(default_factory=dict)
    selected_tables: list[str] = Field(min_length=1)
    cron_expr: str | None = None
    cron_enabled: bool = False

    @field_validator("cron_expr")
    @classmethod
    def _validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return None
        CronTrigger.from_crontab(v)  # raises ValueError si invalide
        return v


class GitSyncExportResult(BaseModel):
    sha: str
    tables_count: int
    rows_exported: int


class GitSyncImportPreview(BaseModel):
    tables: list[dict]   # [{ "table": "users", "to_insert": 5, "to_update": 2, "to_delete": 1 }]


class GitSyncImportResult(BaseModel):
    rows_inserted: int
    rows_updated: int
    rows_deleted: int


class GitSyncCommitDTO(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str
```

### Branchement `main.py`

Dans le `lifespan` :
```python
# Au démarrage (après le pool DB, après backup_scheduler.start())
await git_sync_scheduler.start()

# À l'arrêt (avant la fermeture du pool)
await git_sync_scheduler.stop()
```

Et inclure le router :
```python
from agflow.api.admin import git_sync as git_sync_router
app.include_router(git_sync_router.router)
```

## Frontend

### Client API — `frontend/src/lib/gitSyncApi.ts` (~140 lignes)

9 fonctions correspondant aux endpoints :

```ts
export type GitSyncConfig = {
  repo_url: string;
  auth_mode: 'ssh_key' | 'pat_https' | 'basic_https';
  auth_secret_ref: string;
  branch: string;
  commit_author_name: string;
  commit_author_email: string;
  excluded_columns: Record<string, string[]>;
  selected_tables: string[];
  cron_expr: string | null;
  cron_enabled: boolean;
  last_export_at: string | null;
  last_export_status: 'ok' | 'failed' | null;
  last_export_sha: string | null;
  last_export_error: string | null;
  last_export_tables_count: number | null;
  last_import_at: string | null;
  last_import_status: 'ok' | 'failed' | null;
  last_import_error: string | null;
  last_import_rows_inserted: number | null;
  last_import_rows_updated: number | null;
  last_import_rows_deleted: number | null;
  created_at: string;
  updated_at: string;
};

export type GitSyncConfigUpsert = Omit<GitSyncConfig,
  'last_export_at' | 'last_export_status' | 'last_export_sha' | 'last_export_error' | 'last_export_tables_count' |
  'last_import_at' | 'last_import_status' | 'last_import_error' | 'last_import_rows_inserted' | 'last_import_rows_updated' | 'last_import_rows_deleted' |
  'created_at' | 'updated_at'>;

export type GitSyncCommit = {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_email: string;
  authored_at: string;
  html_url: string;
};

// fetchConfig, upsertConfig, deleteConfig, listAvailableTables,
// testSecretRef, runExport, previewImport, runImport, listCommits
```

### Hook — `frontend/src/hooks/useGitSync.ts` (~80 lignes)

- `useGitSyncConfig()` : `useQuery(['git-sync', 'config'])`, refetchInterval 30s (pour voir les `last_*` se mettre à jour quand le cron tourne).
- `useAvailableTables()` : `useQuery(['git-sync', 'available-tables'])`, staleTime 5min.
- `useGitSyncCommits(limit)` : `useQuery(['git-sync', 'commits', limit], { enabled: config?.repo_url != null })`, refetchInterval 60s.
- `useUpsertConfig()`, `useDeleteConfig()`, `useTestSecretRef()`, `useRunExport()`, `usePreviewImport()`, `useRunImport()` : mutations qui invalident `['git-sync', 'config']` et `['git-sync', 'commits']`.

### Composants UI

**Modification de `SettingsPage.tsx`** : ajouter un onglet « Git Sync » dans le composant `<Tabs>` aux côtés de « Harpocrate ».

**`frontend/src/components/settings/GitSyncTab.tsx`** (~80 lignes — wrapper) :
- Branche sur `useGitSyncConfig()`.
- Si pas de config → CTA « Configurer Git Sync » qui ouvre le dialog.
- Sinon → 3 sections empilées (Config / Actions / History).

**`frontend/src/components/settings/GitSyncConfigSection.tsx`** (~150 lignes) :
- Card avec récap config : repo_url (cliquable → ouvre repo), branch (Badge), auth_mode (Badge), commit_author_*, selected_tables (Badge count + popover liste), excluded_columns (Badge count + popover), cron status (vert/gris).
- Boutons : « Modifier » (ouvre dialog) + « Supprimer la config » (confirmation Dialog).

**`frontend/src/components/settings/GitSyncActionsSection.tsx`** (~120 lignes) :
- 3 boutons :
  - **« Exporter maintenant »** → appelle `useRunExport()`, désactivé pendant l'export, toast résultat (sha + tables_count).
  - **« Aperçu de l'import »** → ouvre dialog Preview.
  - **« Importer depuis Git »** → ouvre dialog Preview avec warning, puis bouton « Lancer l'import ».
- Card « Dernier export » : status badge (ok/failed) + last_export_at + last_export_sha (cliquable → GitHub) + last_export_error (si failed).
- Card « Dernier import » : status badge + last_import_at + counts ins/upd/del + last_import_error.

**`frontend/src/components/settings/GitSyncHistorySection.tsx`** (~80 lignes) :
- Si `parse_repo_url` host == `github.com` : Table des 30 derniers commits (short_sha + author + message + authored_at) — clic ligne = `window.open(html_url, '_blank')`.
- Sinon : message « Liste des commits non disponible pour ce host. Voir le repo : <a href={repo_url}>repo_url</a> ».
- Refresh manuel + auto 60s.

**Dialog config** (`GitSyncConfigDialog.tsx`, ~200 lignes — fichier séparé pour rester sous 300 lignes par fichier) :
- Form complet : repo_url, branch, auth_mode (Select), auth_secret_ref (Input + bouton « Tester la résolution Harpocrate » qui appelle `POST /api/admin/git-sync/test-secret-ref`), commit_author_name/email, selected_tables (multi-select avec recherche, populated depuis `useAvailableTables()`), excluded_columns (JSON editor ou key-value rows), cron_enabled (Checkbox), cron_expr (Input + presets : « Toutes les heures », « Quotidien à 4h », « Hebdo dimanche 2h »).
- Validation Zod côté client : regex repo_url, cron syntax (regex basique), JSON valide pour excluded_columns.
- Submit → `useUpsertConfig()`.

**Dialog Preview import** :
- Affiche les counts par table (Table 3 colonnes : table / to_insert / to_update / to_delete).
- Total en footer.
- 2 boutons : « Annuler » + « Lancer l'import » (rouge, avec warning « Cette action modifie irréversiblement la base »).

**Dialog Import en cours** :
- Loading state pendant l'import.
- Affiche résultat (counts) ou erreur.

### i18n — `frontend/src/i18n/fr.json` & `en.json`

~50 clés sous `settings.gitSync.*` :
```
settings.gitSync.tabLabel
settings.gitSync.empty.title
settings.gitSync.empty.cta
settings.gitSync.config.title
settings.gitSync.config.repoUrl
settings.gitSync.config.branch
settings.gitSync.config.authMode
settings.gitSync.config.authSecretRef
settings.gitSync.config.testHarpocrate
settings.gitSync.config.commitAuthor
settings.gitSync.config.selectedTables
settings.gitSync.config.excludedColumns
settings.gitSync.config.cronExpr
settings.gitSync.config.cronEnabled
settings.gitSync.config.cronPresets.hourly
settings.gitSync.config.cronPresets.daily4am
settings.gitSync.config.cronPresets.weeklySun2am
settings.gitSync.actions.exportNow
settings.gitSync.actions.previewImport
settings.gitSync.actions.runImport
settings.gitSync.actions.importWarning
settings.gitSync.lastExport.title
settings.gitSync.lastExport.statusOk
settings.gitSync.lastExport.statusFailed
settings.gitSync.lastImport.title
settings.gitSync.history.title
settings.gitSync.history.unsupportedHost
settings.gitSync.history.empty
settings.gitSync.dialog.delete.confirm
settings.gitSync.toast.exportSuccess
settings.gitSync.toast.exportFailed
settings.gitSync.toast.importSuccess
settings.gitSync.toast.importFailed
settings.gitSync.toast.harpocrateOk
settings.gitSync.toast.harpocrateFailed
```

## Tests

### Backend (~30 nouveaux tests)

| Fichier | Tests | Type |
|---|---|---|
| `tests/services/test_git_sync_service.py` | upsert/get/delete singleton ; rejet 2e INSERT (CHECK id=1) ; list_available_tables ; record_export_run / record_import_run mettent à jour last_* | integration DB |
| `tests/services/test_git_sync_github_client.py` | parse_repo_url (ssh, https, gitlab non supporté) ; list_commits avec mock httpx (200/401/404/429) | unit |
| `tests/services/test_git_sync_runner.py` | run_export happy path (mock GitService + ExportService) ; run_export KO récupère error sur last_export_* ; run_preview / run_import wrappers OK | integration (mocks SDK) |
| `tests/services/test_git_sync_scheduler.py` | start/stop / reload (1 job singleton si cron_enabled) / trigger_now | unit (mock AsyncIOScheduler) |
| `tests/api/test_admin_git_sync.py` | 9 endpoints : 401/403/200/404, validation cron 422, test-secret-ref ok/ko, run-export 200, preview JSON, import 200, commits format, unsupported_host | integration HTTP (mocks service) |

### Frontend

Vitest sur `useGitSync.ts` (mocks api client) et validations Zod du form (regex repo_url, cron, JSON excluded_columns).

### Validation E2E

`./scripts/run-test.sh` — la suite pytest tourne dans le LXC fresh, les nouveaux tests doivent passer.

**Smoke métier post-déploiement** (manuel, dans l'ordre) :
1. Créer un coffre Harpocrate default (déjà fait).
2. Créer un secret Git dans Harpocrate (ex: PAT GitHub) sous `agflow_default/git/agflow-sync`.
3. Aller dans `/settings` → onglet « Git Sync » → bouton « Configurer ».
4. Remplir : repo_url=`https://github.com/<owner>/<repo>`, auth_mode=`pat_https`, auth_secret_ref=`agflow_default/git/agflow-sync`, branch=`main`, sélection de tables non-sensibles (`infra_categories`, `infra_named_types`).
5. Cliquer « Tester la résolution Harpocrate » → toast OK.
6. Save → la card de config s'affiche.
7. Bouton « Exporter maintenant » → vérifier que le repo GitHub contient `docker/datas/*.csv` + `dependencies.json` + commit fait avec le bon message d'auteur.
8. Section « Historique GitHub » : vérifier que le commit apparaît, clic = ouvre la page commit GitHub dans un nouvel onglet.
9. Modifier la config : changer `branch=test-import`, save.
10. Sur une autre instance (LXC vierge ou refresh) : configurer le même repo, brancher sur `branch=test-import`, bouton « Aperçu import » → vérifier les comptes attendus, bouton « Importer » → vérifier en DB que les rows sont créées.
11. Activer le cron `*/2 * * * *` (toutes les 2 min), attendre 2 min, vérifier qu'un nouveau commit apparaît automatiquement.

C'est précisément le smoke qui va révéler les bugs SDK (cas réel : repo GitHub vrai, DB peuplée, FK cycliques éventuelles).

## Scope V1 livré

- ✅ Table singleton `git_sync_config` (migration 110)
- ✅ Service `git_sync_service` (CRUD config + wrappers SDK + last_* tracking)
- ✅ Service `git_sync_github_client` (parse repo_url + appel GitHub API)
- ✅ Worker `git_sync_scheduler` dédié (AsyncIOScheduler + tick re-sync 30s)
- ✅ 9 endpoints API admin
- ✅ Onglet « Git Sync » dans /settings (sous-composants Config/Actions/History)
- ✅ Dialog config (form complet + bouton test Harpocrate) + dialog Preview + dialog Import
- ✅ Historique GitHub affiché + clic redirige vers GitHub
- ✅ i18n FR/EN (~50 clés)

## Out-of-scope V1 (différé)

- ❌ Multi-config (toujours singleton)
- ❌ Support GitLab / Bitbucket API pour l'historique (juste lien externe + message unsupported_host)
- ❌ Sélection de commit historique pour l'import (V1 = HEAD uniquement ; le SDK supporte `target_commit` mais l'UI ne l'expose pas)
- ❌ Diff visuel des changements (juste les counts)
- ❌ Webhook GitHub pour auto-import sur push
- ❌ Compression des CSV exportés
- ❌ Notifications sur échec (email/Slack)

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Bugs SDK révélés en intégration (DB réelle, FK cycliques, gros volumes) | Tests E2E manuel obligatoire (smoke métier). Tout fix nécessaire au SDK est inclus dans le chantier. |
| Admin exporte `users` / `harpocrate_vaults` par erreur → leak | Warning UI dans la sélection des tables. Pas de blacklist hardcodée (choix utilisateur). Documenter dans la spec/UI. |
| Token GitHub PAT exposé dans les logs | Token vit uniquement dans Harpocrate. Au moment de l'appel API, header `Authorization` envoyé sans logger. URL GitHub API loggée sans token. |
| Rate limit GitHub (60/h sans auth, 5000/h avec PAT) | UI refresh les commits toutes les 60s seulement. Si rate-limited → toast + retry après reset. PAT recommandé. |
| Cron + bouton manuel en concurrence (overlap) | `max_instances=1` par job APScheduler. Si manual trigger pendant cron tourne → skip ou queue selon APScheduler. |
| Import casse la DB (FK violation, rows orphelines) | Transaction unique (phases 4+5 du SDK), rollback automatique sur exception. Tmp tables purgées dans finally. Documenté : faire un backup AVANT l'import via le bouton « Sauvegarder maintenant » de la page Backups. |
| Repo Git inaccessible (DNS, auth) lors d'un cron | Job APScheduler chope l'exception, log error, met `last_export_status='failed'`. UI montre badge rouge. Pas de blocage backend. |
| `auth_secret_ref` invalide (typo, secret absent) | Bouton « Tester la résolution Harpocrate » dans le dialog config → appel `vault_client.resolve_ref()` → toast OK/KO avant de sauvegarder. |
| Config singleton supprimée alors qu'un job tourne | Job en cours finit normalement (lit la config au début). `git_sync_scheduler.reload()` au prochain tick voit la config absente → remove le job. |
| Sélection de tables avec FK croisée (cycle) → `DependencyResolveError` | L'exception remonte → UI affiche un toast clair avec les tables impliquées. L'admin déselectionne pour briser le cycle. |

## Effort estimé

**~14-16 commits, 2-3 jours wall time** :

- **Jour 1** : migration 110 + service config (CRUD + list_available_tables) + tests + github_client (parse_repo_url + list_commits) + tests.
- **Jour 2** : runner wrapper SDK + scheduler dédié + 9 endpoints API + tests HTTP + branchement main.py.
- **Jour 3** : frontend (api client + hook + onglet + 3 sous-composants + dialogs + i18n) + validation E2E `run-test.sh` + smoke métier manuel.

## Conventions de commit

- `feat(git-sync-db):` — migration 110
- `feat(git-sync-service):` — service config + github_client + runner
- `feat(git-sync-scheduler):` — APScheduler worker
- `feat(git-sync-api):` — 9 endpoints admin
- `feat(git-sync-ui):` — onglet + composants + i18n
- `chore(git-sync):` — modifications mineures
- `docs(git-sync):` — doc admin si besoin
