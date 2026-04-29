# Spec — Bouton "Exporter" du volume `data/`

> **Statut** : design validé 2026-04-29 — prêt pour le plan d'implémentation
> **Auteur** : brainstorming Claude + utilisateur
> **Initiative parente** : préalable à la migration livraison vers Swarm + CI GHCR (cf. `2026-04-29-github-build-images-design.md`)

## 1. Contexte et objectif

Avant de basculer la chaîne de livraison vers Docker Swarm + CI GitHub, il est nécessaire de pouvoir **récupérer en un clic le contenu du volume mappé `./data/`** depuis l'app web.

Le volume contient les artefacts non-DB de la plateforme :

- `avatars/` (images générées par DALL·E, ~23 MB sur LXC 201 au 2026-04-29)
- `templates/` (templates filesystem Jinja distincts de la table `scripts`)
- `roles/`, `agents/`, `registries/`, `platforms/`, `services/`, `products/`, `projects/`, `sandbox/`
- Dockerfiles fichiers (déclinaisons par agent : `aider/`, `claude/`, `codex/`, `gemini/`, `mistral/`, `naked/`, `open-code/`)
- Petits fichiers JSON/env de config (`ai-providers.json`, `dozzle-agents.env`)

Volume total estimé sur LXC 201 ≈ 25 MB au 2026-04-29 ; conçu pour rester gérable dans le futur via streaming.

**Hors scope** : la base PostgreSQL. Le dump DB sera traité dans une initiative ultérieure ("on investiguera la base après").

## 2. Décisions verrouillées

| Décision | Choix |
|----------|-------|
| Périmètre | `./data/` complet, **rien d'autre** |
| Format | `zip` (Windows-friendly) |
| Permissions | **Admin uniquement** (`require_admin`) |
| Nommage | `agflow-data-YYYYMMDD-HHMMSS.zip` (timestamp UTC) |
| HTTP method | `GET` (pas d'effet de bord) |
| Streaming | Oui, via `StreamingResponse` + lib zip-streaming |
| Source path | `Settings.data_dir` = env `AGFLOW_DATA_DIR` (= `/app/data` côté container) |
| Audit log | Une ligne `structlog` `info("system.export", user_id=..., size_bytes=..., duration_s=...)` à la fin du stream |

## 3. Architecture

### 3.1 Backend

```
backend/src/agflow/
├── api/admin/system.py            # NOUVEAU router — GET /api/admin/system/export
├── services/system_export.py      # NOUVEAU service — génération du zip en streaming
└── main.py                        # Enregistrer le nouveau router
```

#### Router `api/admin/system.py`

```python
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from agflow.auth.deps import require_admin, AuthContext
from agflow.config import get_settings
from agflow.services.system_export import iter_data_zip, export_filename

router = APIRouter(prefix="/system", tags=["admin-system"])

@router.get("/export")
async def export_data_volume(
    auth: AuthContext = Depends(require_admin),
) -> StreamingResponse:
    settings = get_settings()
    filename = export_filename()
    return StreamingResponse(
        iter_data_zip(settings.data_dir, user_id=auth.user_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

#### Service `services/system_export.py`

```python
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
import structlog
from stream_zip import async_stream_zip, ZIP_64

logger = structlog.get_logger(__name__)

def export_filename() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"agflow-data-{ts}.zip"

async def iter_data_zip(root: Path, *, user_id: str) -> AsyncIterator[bytes]:
    started = datetime.now(timezone.utc)
    total = 0
    files_iter = _walk_data(root)               # async generator yielding (member_path, mtime, perms, content_iter)
    async for chunk in async_stream_zip(files_iter):
        total += len(chunk)
        yield chunk
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info("system.export", user_id=user_id, size_bytes=total, duration_s=duration)
```

- Utilise [`stream-zip`](https://github.com/uktrade/stream-zip) (BSD, async-friendly, ZIP64-ready, pas de fichier temporaire)
- `_walk_data(root)` énumère récursivement avec `Path.rglob("*")` en filtrant les fichiers (pas les dirs vides)
- Chemins dans le zip = relatifs à `root` (pas le chemin absolu du container)
- Si `root` n'existe pas ou est vide → produit un zip vide valide (ne crash pas)

### 3.2 Frontend

```
frontend/src/components/layout/TopBar.tsx   # MODIFIÉ — ajouter bouton Export
frontend/src/i18n/fr.json                   # MODIFIÉ — clés topbar.export*
frontend/src/i18n/en.json                   # MODIFIÉ — clés topbar.export*
```

#### Modification `TopBar.tsx`

- Nouveau bouton à **gauche du bouton Search** (l'utilisateur a demandé "barre de titre en haut à droite", on respecte la zone droite).
- Icône `Download` de `lucide-react`.
- Visible uniquement si `useAuth().isAdmin === true` (hook existant `frontend/src/hooks/useAuth.ts`)
- Le JWT est en `localStorage` (pas en cookie), donc on ne peut PAS faire `window.location.href` (le navigateur n'enverrait pas le `Authorization: Bearer`). On télécharge via `axios` en `responseType: "blob"` puis on déclenche le download via un anchor temporaire :
  ```ts
  const r = await api.get("/admin/system/export", { responseType: "blob" });
  const cd = r.headers["content-disposition"] as string | undefined;
  const fname = cd?.match(/filename="([^"]+)"/)?.[1] ?? "agflow-data.zip";
  const url = URL.createObjectURL(r.data as Blob);
  const a = document.createElement("a");
  a.href = url; a.download = fname; a.click();
  URL.revokeObjectURL(url);
  ```
- Limite : `responseType: "blob"` charge tout en mémoire navigateur avant download. Acceptable jusqu'à ~500 MB ; au-delà il faudra passer à un streaming côté client (Fetch API + `ReadableStream` + File System Access API). Documenté en risque section 7.
- Pas de feedback de progression dans cette V1 (volume petit ~25 MB) — état "loading" sur le bouton suffit (icône spinner pendant la requête)

#### i18n

```json
{
  "topbar": {
    "export": "Exporter les données",
    "export_tooltip": "Télécharger une archive ZIP du volume data/"
  }
}
```

## 4. Tests

### 4.1 Backend (`backend/tests/api/admin/test_system_export.py`)

| # | Cas | Attendu |
|---|-----|---------|
| 1 | `GET /api/admin/system/export` sans token | `401` |
| 2 | Avec token `viewer` ou `operator` | `403` |
| 3 | Avec token `admin`, `data_dir` rempli | `200` + `application/zip` + header `Content-Disposition` matchant `agflow-data-YYYYMMDD-HHMMSS.zip` |
| 4 | Le zip téléchargé est valide (ouvrable via `zipfile.ZipFile`) et contient les fichiers du fixture | OK |
| 5 | `data_dir` vide → zip vide mais valide | `200`, archive de 0 fichier |
| 6 | `data_dir` n'existe pas → zip vide mais valide (ne crash pas) | `200` |

Fixture : créer un `tmp_path` avec quelques fichiers + sous-dossiers, override `Settings.data_dir`.

### 4.2 Frontend (`frontend/src/components/layout/TopBar.test.tsx` — NOUVEAU)

| # | Cas | Attendu |
|---|-----|---------|
| 1 | User admin → bouton Export visible | OK |
| 2 | User non-admin → bouton Export absent | OK |
| 3 | Click sur Export → appelle `api.get("/admin/system/export", { responseType: "blob" })` et déclenche un download (anchor click) | OK (mock `api.get`, `URL.createObjectURL`, anchor) |
| 4 | Pendant l'attente de la réponse, l'icône passe en spinner et le bouton est désactivé | OK |

## 5. Dépendances à ajouter

| Lib | Where | Pourquoi |
|-----|-------|----------|
| `stream-zip` | `backend/pyproject.toml` | Streaming zip async natif, pas de tempfile, ZIP64 ready |

## 6. Plan de livraison

Une seule branche, un seul PR. Étapes :

1. Backend : ajouter dépendance, écrire service + router + tests, lancer `uv run pytest`
2. Frontend : modifier TopBar + i18n + tests, lancer `npm test` + `npx tsc --noEmit`
3. Déployer sur LXC 201 (script `deploy.sh` actuel — la migration CI vient APRÈS cette feature)
4. Tester manuellement : login admin → click Exporter → vérifier téléchargement + ouvrir le zip → comparer le contenu avec `ls /root/agflow.docker/data/` côté LXC
5. **Récupération utilisateur** : l'utilisateur télécharge l'archive depuis sa session admin et la met de côté avant de démarrer le chantier CI GHCR

## 7. Risques et mitigation

| Risque | Mitigation |
|--------|------------|
| Volume devient gros (avatars accumulés) → timeout HTTP | Streaming + ZIP64 dès la V1, pas de buffering serveur. Si besoin, ajouter timeout serveur élevé (ex: 600s) et logger en cas d'interruption client. |
| Volume devient très gros (>500 MB) → blob navigateur sature la RAM | V1 acceptable jusqu'à ~500 MB. Au-delà, migrer le frontend vers Fetch streaming + File System Access API (post-V1). |
| Concurrence : un autre process écrit dans `data/` pendant l'export | Acceptable en V1 (best-effort snapshot, pas de garantie de cohérence transactionnelle). À documenter dans le tooltip si critique. |
| Bypass admin via API directe | Le `require_admin` est appliqué côté backend, le frontend ne fait que cacher le bouton. La protection est bien à la bonne couche. |

## 8. Hors scope (ce qu'on ne fait PAS dans cette spec)

- Dump de la DB Postgres (initiative séparée future)
- Export programmé / cron / S3 (one-shot manuel uniquement)
- Restauration / import en sens inverse (extraction manuelle pour l'instant)
- UI de progression (volume actuel petit)
- Sélection partielle (sous-dossier précis) — toujours `./data/` complet

## 9. Critères d'acceptation

- [ ] `GET /api/admin/system/export` renvoie un zip valide pour un admin authentifié
- [ ] Endpoint refuse 401/403 pour non-admin
- [ ] Bouton visible dans la topbar pour les admins, masqué pour les autres
- [ ] Téléchargement déclenché par click, filename horodaté UTC
- [ ] Tests backend + frontend passent
- [ ] `ruff check` + `tsc --noEmit` propres
- [ ] Déployé sur LXC 201, archive téléchargée et ouverte côté Windows, contenu cohérent avec le volume LXC
