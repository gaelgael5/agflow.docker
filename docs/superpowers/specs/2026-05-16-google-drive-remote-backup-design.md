# Connexion distante Google Drive pour les remote backups

**Date** : 2026-05-16
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`
**Référence externe** : feature `gdrive` livrée dans le repo Harpocrate (branche `feat/local-admin-auth`, commits `d75e8c3` → `36bca99`). On reproduit l'architecture, adaptée à notre stack.

## Objectif

Ajouter `kind='gdrive'` au catalogue des connexions distantes (`remote_backup_connections`) pour permettre :

- Upload des backups Postgres vers un dossier Google Drive dédié (en plus des kinds existants `sftp`, `s3`, `ftps`).
- Restore depuis Drive via le flow `pull_remote_to_local` existant (liste + download du dossier).
- Setup admin via OAuth 2.0 user-delegated (Client ID/Secret saisis dans le formulaire, popup Google, callback).

Le provider Drive devient compatible avec le `RemoteBackupProvider` Protocol existant — donc compatible immédiat avec tous les flows upload/list/download/restore déjà en place.

## Contexte

L'app a actuellement 3 providers remote-backups : `sftp`, `s3`, `ftps`. Ils suivent un `Protocol` commun (`test_connection`, `upload_stream`, `list_remote`, `download_stream`) instancié via `factory.get_provider(kind, config, credentials)`. Les credentials sensibles (passwords SFTP, secret keys S3) vivent dans le coffre Harpocrate par défaut, référencés depuis la colonne `vault_secret_path` de `remote_backup_connections`.

On vient de livrer le système de coffres Harpocrate multi-coffres (`harpocrate_vaults` + `vault_client.py` multi-coffres + UI `/settings`). Le pattern de stockage des secrets est `${vault://<vault_name>:<path>}` injecté dans une colonne texte.

Pas de provider OAuth Google avant cette feature — gdrive est le premier. L'architecture mise en place doit pouvoir accueillir Gmail, Dropbox, OneDrive plus tard sans refonte majeure.

## Décisions structurantes (déjà tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Auth | OAuth 2.0 user-delegated | Pattern standard Google. Pas d'API key sans utilisateur final. |
| 2 | Client OAuth (Client ID / Secret) | Saisis par l'admin dans le formulaire | Chaque déploiement utilise son propre projet Google Cloud. Évite à l'app de partager un Client ID central. |
| 3 | Scope OAuth Drive | `https://www.googleapis.com/auth/drive.file` | **Non-sensitive** côté Google (pas de verification process). Donne accès lecture/écriture/suppression aux **fichiers créés par l'app uniquement**. Idéal pour notre cas (on ne touche pas le reste du Drive utilisateur). |
| 4 | Stockage des credentials OAuth (refresh_token, client_secret) | Coffre Harpocrate par défaut | Cohérent avec infra_machines/certs/swarm. Path-style `remote_backups/<connection_id>/oauth`. ⚠️ Bug SDK Harpocrate path-style bloque la lecture tant que pas patché upstream — fix en cours. |
| 5 | Round-trip OAuth (state token) | Nouvelle table `oauth_pending_session` | Pattern Harpocrate. Scalable à d'autres providers OAuth. Audit-friendly. TTL 10 min + reaper. |
| 6 | Organisation des endpoints OAuth | Tout dans le router existant `remote_backup_connections.py` | Limite 300 lignes potentiellement frôlée (175 actuelles + ~140 prévus). Split en sous-module si dépassement constaté à l'implémentation. |
| 7 | `test_connection` pour Drive | `drive.files.list(q="'<folder_id>' in parents")` (1 page suffit) | Cohérent avec les autres providers qui listent leur folder cible. |
| 8 | Résolution du `folder_name` au callback | Always-create avec suffixe daté si conflit | Plus simple à coder. L'admin assume la « pollution » éventuelle du Drive cible. |

## Modèle de données

### Migration A — étendre le CHECK `kind`

```sql
-- backend/migrations/107_remote_backup_kinds_gdrive.sql

ALTER TABLE remote_backup_connections DROP CONSTRAINT remote_backup_connections_kind_check;
ALTER TABLE remote_backup_connections ADD CONSTRAINT remote_backup_connections_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
```

### Migration B — table `oauth_pending_session`

```sql
-- backend/migrations/108_oauth_pending_session.sql

CREATE TABLE oauth_pending_session (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    state                    text NOT NULL UNIQUE,                       -- token aléatoire (CSRF)
    kind                     text NOT NULL CHECK (kind IN ('gdrive')),   -- élargi plus tard
    actor_user_id            uuid REFERENCES users(id) ON DELETE SET NULL,
    redirect_uri             text NOT NULL,
    form_data                jsonb NOT NULL DEFAULT '{}'::jsonb,         -- name, folder_name, client_id (publics)
    client_secret_encrypted  bytea NOT NULL,                              -- pgcrypto PGP_SYM_ENCRYPT via HARPOCRATE_DEK
    expires_at               timestamptz NOT NULL,
    consumed_at              timestamptz,                                 -- non-null = utilisé une fois, refusé après
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_pending_expires_at ON oauth_pending_session(expires_at) WHERE consumed_at IS NULL;
```

### Layout `config` JSONB des rows gdrive

Après création OAuth réussie :

```json
{
    "client_id": "123456789-abc.apps.googleusercontent.com",
    "redirect_uri": "https://agflow.example.com/api/admin/backup-remotes/oauth/gdrive/callback",
    "folder_name": "agflow-backups",
    "folder_id": "1a2B3c4D5eFgH...",
    "user_email": "ops@example.com",
    "credentials_ref": "${vault://default:remote_backups/<connection_id>/oauth}"
}
```

### Contenu du secret stocké dans Harpocrate

Sous le path `remote_backups/<connection_id>/oauth` :

```json
{
    "client_secret": "GOCSPX-...",
    "refresh_token": "1//0g...",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scope": "https://www.googleapis.com/auth/drive.file",
    "granted_at": "2026-05-16T12:34:56Z"
}
```

L'access_token n'est jamais persisté : recalculé à chaque opération via `refresh()`.

## Architecture backend

### Nouveau : `services/remote_backup_providers/gdrive_client.py` (~120 lignes)

Couche fine au-dessus du SDK Google. Pas d'I/O réseau direct dans `gdrive_provider.py` — tout passe par ici. Permet de mocker proprement le SDK dans les tests.

```python
def build_credentials(creds_dict: dict) -> google.oauth2.credentials.Credentials
def build_drive_service(creds: Credentials) -> Resource              # googleapiclient.discovery
def build_flow(client_id, client_secret, redirect_uri, scopes) -> google_auth_oauthlib.flow.Flow
async def fetch_user_email(creds: Credentials) -> str                # via oauth2.userinfo
async def refresh(creds: Credentials) -> Credentials                 # rotation access_token (sync wrapped)
```

### Nouveau : `services/remote_backup_providers/gdrive_provider.py` (~150 lignes)

```python
class GoogleDriveProvider:
    def __init__(self, config: dict, credentials: dict) -> None:
        self._folder_id = config["folder_id"]
        self._creds = gdrive_client.build_credentials(credentials)

    async def test_connection(self, path: str) -> None: ...
    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int: ...
    async def list_remote(self, path: str) -> list[RemoteFile]: ...
    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]: ...
```

- `path` est ignoré par tous les providers Google (Drive n'a pas de sous-path interne au folder configuré). Documenté en docstring + raison d'être (préserve la signature du Protocol).
- `upload_stream` : streame le source dans un tempfile (comme SFTP/FTPS le font), puis resumable upload via `MediaFileUpload(resumable=True)`. Suppression du tempfile après. Retourne `bytes_written`.
- `list_remote` : `drive.files.list(q="'<folder_id>' in parents and trashed=false", fields="files(id, name, size, modifiedTime)")`. Mappe chaque file en `RemoteFile(filename, size_bytes, last_modified)`.
- `download_stream` : `drive.files.list(q="name='<filename>' and ...")` pour résoudre l'ID, puis `MediaIoBaseDownload` streamé en chunks 256 KB.
- Toutes les exceptions Google (`HttpError` 4xx/5xx) sont mappées en `RemoteBackupProviderError` avec message tronqué (200 chars).

### Modif : `factory.py`

Ajoute une case `"gdrive"` qui instancie `GoogleDriveProvider`.

### Nouveau : `services/gdrive_oauth_session.py` (~180 lignes)

Orchestration du flow OAuth. Toutes les fonctions sont async + utilisent le pool DB existant.

```python
async def start_session(
    *, actor_user_id: UUID, name: str, folder_name: str,
    client_id: str, client_secret: str, redirect_uri: str,
) -> tuple[str, str]:                                     # (state, authorize_url)

async def consume_session(
    *, state: str, code: str,
) -> dict:                                                # {connection_id, user_email, folder_id, ...}

async def get_session(state: str) -> dict | None:        # status polling

async def reauthorize(
    *, connection_id: UUID, actor_user_id: UUID,
) -> tuple[str, str]:                                     # (state, authorize_url)
```

Détails :
- `start_session` : génère `state = secrets.token_urlsafe(32)`, écrit la pending row avec `form_data = {name, folder_name, client_id, client_secret_ref}` (le secret transite par une row vault temporaire chiffrée — voir détail § Sécurité), `expires_at = now() + 10 min`. Construit l'URL d'autorisation Google via `flow.authorization_url(prompt='consent', access_type='offline', state=state)`.
- `consume_session` : lookup pending row par `state`, refuse si `consumed_at IS NOT NULL` ou `expires_at < now()`. Déchiffre `client_secret_encrypted` via `PGP_SYM_DECRYPT(... , settings.harpocrate_dek)`. Marque `consumed_at = now()`. Échange `code` → tokens via `flow.fetch_token(code=code)`. Fetch `user_email` via `oauth2.userinfo`. **Folder Drive (always-create)** : `drive.files.list(q="name='<folder_name>' and mimeType='application/vnd.google-apps.folder' and trashed=false")`. Si ≥ 1 résultat → créer `<folder_name> (YYYY-MM-DD HH:MM)` avec un suffixe daté pour rendre le nom unique. Sinon → créer `<folder_name>` tel quel. **On ne réutilise jamais un dossier existant** — chaque connexion a son propre dossier. Push credentials dans Harpocrate au path `remote_backups/<connection_id>/oauth`. INSERT row `remote_backup_connections` avec config complète. Audit log `remote_backup.gdrive.oauth_completed`.
- `get_session` : retourne `{status: 'pending'|'completed'|'failed', connection_id?, user_email?, folder_id?, error?}` pour le polling frontend.
- `reauthorize` : récupère la connexion, démarre un nouveau pending réutilisant `client_id` actuel + le `client_secret` (déchiffré depuis Harpocrate). Au callback, met à jour le secret vault (rotation refresh_token).

### Modif : `api/admin/remote_backup_connections.py` (+~140 lignes)

5 nouveaux endpoints sous `/api/admin/backup-remotes/oauth/gdrive` + 1 endpoint générique `/reauthorize` :

| Méthode | Path | Réponse | Codes erreur |
|---|---|---|---|
| GET | `/redirect-uri` | `{redirect_uri}` (pour pré-remplissage UI) | — |
| POST | `/start` | `{state, authorize_url}` (body: `{name, folder_name, client_id, client_secret}`) | 422 validation |
| GET | `/callback?code=&state=` | HTML qui ferme le popup + postMessage à l'opener | 400 invalid state, 410 expired |
| GET | `/session/{state}` | `{status, connection_id?, ...}` | 404 unknown state |
| POST | `/connections/{id}/reauthorize` (générique kind-agnostic, accepte gdrive uniquement V1) | `{state, authorize_url}` | 404, 400 si kind unsupported |

Le POST CRUD générique existant (`POST /api/admin/backup-remotes/connections` body `{kind:'gdrive', ...}`) retourne 400 « use /oauth/gdrive/start instead ». Empêche la création silencieuse d'une connexion gdrive sans credentials.

### Modif : `main.py` (lifespan)

Nouveau worker `oauth_pending_reaper` démarré au startup, tick 5 min, `DELETE FROM oauth_pending_session WHERE expires_at < now() - interval '1 hour' OR consumed_at IS NOT NULL`. Log structuré du nombre de rows purgées.

### Audit log

Actions sous `remote_backup.gdrive.oauth_*` (utilise le pattern logs structurés existant ou le module audit_service si dispo) :

- `oauth_started` — metadata : `state`, `name`, `folder_name`, `actor_user_id`
- `oauth_completed` — metadata : `connection_id`, `user_email`, `folder_id`, `actor_user_id`
- `oauth_failed` — metadata : `state`, `error` (200 chars max), `actor_user_id`
- `oauth_reauthorized` — metadata : `connection_id`, `user_email`, `actor_user_id`

**Jamais** de `client_secret`, `refresh_token`, `access_token`, `code` dans les logs.

### Dépendances Python

À ajouter dans `backend/pyproject.toml` ET `backend/Dockerfile` (les 2 listes sont désynchronisées, leçon Harpocrate) :

- `google-auth>=2.30,<3`
- `google-auth-oauthlib>=1.2,<2`
- `google-api-python-client>=2.130,<3`

## Architecture frontend

### Nouveau : `lib/gdriveOAuth.ts` (~110 lignes)

Helper de gestion du popup + polling.

```typescript
export class PopupBlockedError extends Error {}
export class OAuthAbortedError extends Error {}
export class OAuthError extends Error {}

export async function runGDriveOAuthFlow(params: {
  authorizeUrl: string;
  state: string;
}): Promise<{ connectionId: string; userEmail: string; folderId: string }>

export async function runGDriveReauthorize(connectionId: string): Promise<void>
```

Ouvre `window.open(authorizeUrl)`. Si bloqué → `PopupBlockedError`. Poll `GET /session/{state}` toutes les 1.5s, timeout 5 min, résout sur `status=completed`, rejette sur `status=failed` ou popup fermée par l'user (`OAuthAbortedError`).

### Modif : `lib/<adminApi>.ts`

Ajoute :
```typescript
startGDriveOAuth(payload) -> { state, authorize_url }
fetchGDriveOAuthSession(state) -> { status, connection_id?, ... }
fetchGDriveRedirectUri() -> { redirect_uri }
reauthorizeRemoteBackup(id) -> { state, authorize_url }   // kind-agnostic
```

### Nouveau : `components/GDriveFields.tsx` (~250 lignes)

Wizard 3 phases avec state local React.

**Phase 1 — Setup** : champs `name` (libellé), `client_id`, `client_secret` (input password), `folder_name` (défaut `agflow-backups`). Encadré explicatif avec lien vers `docs/admin/gdrive-setup.md`. Bouton « Autoriser dans Google Drive ».

**Phase 2 — En cours** : spinner + message. Gestion `PopupBlockedError` → message « autorise les popups pour ce site ».

**Phase 3 — Confirmé** : affiche `user_email` détecté + `folder_id` créé. Boutons « Enregistrer » (ferme le modal) ou « Recommencer ».

Validation Zod (phase 1) :
- `name` ≥ 1
- `client_id` matche `[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com`
- `client_secret` ≥ 1
- `folder_name` ≥ 1

Si dépassement 300 lignes : extraire phases en sous-composants `GDrivePhase{Setup,Auth,Confirmed}.tsx`.

### Modif : `lib/<schema-zod>.ts`

Étend l'enum `kind` à `'sftp' | 's3' | 'ftps' | 'gdrive'`. Ajoute interface `GDriveConfig { client_id, redirect_uri, folder_name, folder_id, user_email, credentials_ref }`. `RemoteBackupConnection` devient union discriminée sur `kind`.

### Modif : page admin backup-remotes

- Modal de création : sélecteur `kind` → ajouter option « Google Drive ». Quand `kind==='gdrive'` → render `<GDriveFields />`.
- Tableau : pour `kind==='gdrive'`, colonne « cible » affiche `user_email` + `folder_name`.
- Bouton « Re-autoriser » : visible sur les lignes `kind==='gdrive'`. Au clic → `runGDriveReauthorize(id)`.

### Modif : i18n FR + EN (~25 clés chacune)

Sous `backups.gdrive.*` : `phaseSetupTitle`, `phaseAuthInProgress`, `phaseConfirmedTitle`, `fieldClientId`, `fieldClientIdHint`, `fieldClientSecret`, `fieldFolderName`, `fieldFolderNameHint`, `btnAuthorize`, `btnRestart`, `btnSave`, `errorPopupBlocked`, `errorAborted`, `errorGeneric`, `confirmedUserEmail`, `confirmedFolderCreated`, `confirmedFolderReused`, `kindLabel`, `tableTargetEmail`, `tableTargetFolder`.

## Documentation

### Nouveau : `docs/admin/gdrive-setup.md`

Guide opérateur pour préparer un projet Google Cloud :

1. Créer un projet Google Cloud (Console GCP)
2. Activer **Google Drive API**
3. Configurer l'**OAuth consent screen** (type External, ajouter scope `drive.file`)
4. Créer un identifiant OAuth client de type **Web application**
5. Ajouter l'URI de redirection : `<your-host>/api/admin/backup-remotes/oauth/gdrive/callback` (le récupérer via le bouton « Copier l'URI » dans le wizard)
6. Récupérer `Client ID` + `Client secret`, les coller dans le wizard agflow

Section limitations :
- Drive permet 15 GB gratuits par compte Google
- Quota global 750 GB/jour upload
- Pas de sub-folders dans le folder cible (V1)

## Tests

### Backend (~30 tests)

| Fichier | Tests | Type |
|---|---|---|
| `tests/services/test_gdrive_client.py` | build_credentials/build_flow/fetch_user_email/refresh (mock SDK Google) | unit |
| `tests/services/test_gdrive_provider.py` | les 4 méthodes Protocol + mapping erreurs Google → RemoteBackupProviderError | unit |
| `tests/services/test_gdrive_oauth_session.py` | start_session crée pending / consume_session happy path / consume rejette consumed / consume rejette expiré / search-or-create folder (3 cas) / reauthorize | unit (vault_mock + mock gdrive_client) |
| `tests/services/test_oauth_pending_reaper.py` | reaper purge expirés + consumed | unit |
| `tests/api/test_admin_backup_remotes_oauth_gdrive.py` | les 5 endpoints : auth, viewer 403, payloads invalides 422, happy path mockés | integration HTTP |
| `tests/test_remote_backup_factory.py` | étend pour case 'gdrive' | unit |

### Frontend

`vitest` sur `gdriveOAuth.ts` (mock window.open + setInterval) et `GDriveFields.tsx` (validation Zod, transition de phases, gestion erreurs).

### Validation E2E

Via `./scripts/run-test.sh` standard. Le test 8 (pytest backend) inclut les ~30 tests gdrive avec mocks → tous verts. Le smoke métier réel (création connexion via OAuth + envoi de backup) ne sera validable qu'après le fix SDK Harpocrate path-style. À ce moment-là, relance run-test + smoke E2E manuel sur LXC live.

## Sécurité

- `client_secret` jamais loggé. Transite uniquement entre :
  1. UI → POST /start (HTTPS)
  2. Pending row colonne `client_secret_encrypted` (chiffré pgcrypto PGP_SYM_ENCRYPT via HARPOCRATE_DEK)
  3. Au callback : déchiffré (PGP_SYM_DECRYPT), utilisé pour `flow.fetch_token()`, puis re-chiffré dans Harpocrate au path final `remote_backups/<id>/oauth`
  4. Pending row marquée `consumed_at` puis purgée par le reaper
- `refresh_token` jamais loggé. Persisté chiffré dans Harpocrate (pgcrypto PGP_SYM_ENCRYPT via DEK).
- `access_token` jamais persisté. Recalculé via `refresh()` à chaque opération.
- `state` token : `secrets.token_urlsafe(32)` (256 bits entropie). UNIQUE constraint DB + check `consumed_at IS NULL`.
- Endpoints `/oauth/gdrive/*` derrière `require_admin`. Le `/callback` est public (Google appelle sans cookie session) mais validé par le `state` token.
- Audit log de toutes les actions OAuth.

## Scope V1

### Livré
- ✅ kind=gdrive activable dans le catalogue
- ✅ Setup via wizard OAuth (saisie ClientID/Secret + folder, popup Google, callback)
- ✅ Upload backup vers Drive (resumable)
- ✅ List/download depuis Drive (cohérent avec sftp/s3/ftps)
- ✅ Restore flow remote-backups marche pour gdrive
- ✅ Re-autoriser une connexion existante
- ✅ Purge auto des pending OAuth expirés
- ✅ Audit log des actions OAuth
- ✅ Doc admin Google Cloud Console

### Out-of-scope (différé V2+)
- ❌ Pagination de `list_remote` au-delà de la 1ère page Drive (~1000 fichiers max)
- ❌ Sub-folders dans le folder cible (`path` toujours ignoré dans le provider)
- ❌ Vérification proactive du quota Drive (15 GB compte gratuit) — l'upload plante avec 403 si plein
- ❌ Multi-comptes Google sur une même connexion
- ❌ Gmail (chantier séparé si besoin)
- ❌ Drive shared drives (Team Drives) — la V1 vise le My Drive de l'utilisateur

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Bug SDK Harpocrate path-style bloque le read des credentials → upload réel KO | Fix SDK en cours upstream. Tests unitaires complets côté nous avec mocks. Smoke E2E métier déclenché après mise à jour SDK. |
| Refresh token Google révoqué par l'utilisateur | Endpoint `reauthorize` couvre. Le provider lève une erreur claire si `invalid_grant` 400. |
| Quota Drive plein pendant un upload | L'erreur 403 Google est propagée en `RemoteBackupProviderError`. Message clair à l'admin. Pas de retry automatique. |
| Dérive Dockerfile vs pyproject.toml | Au commit `feat(gdrive-deps)`, vérifier les 2 fichiers en parallèle. Run-test build l'image → dépendances manquantes détectées immédiatement. |
| Composant `GDriveFields.tsx` dépasse 300 lignes | Extraction des 3 phases en sous-composants `GDrivePhase{Setup,Auth,Confirmed}.tsx`. |
| Verification Google scope `drive.file` | Non requise (scope non-sensitive). Si jamais Google change sa politique, fallback documenté dans le guide admin. |
| `state` token collision (très improbable) | UNIQUE constraint DB lève l'erreur, l'utilisateur recommence le flow. |

## Effort estimé

~12-15 commits, **2-3 jours wall time**, découpés en 3 jours :

- **Jour 1** : migrations + provider + client + factory + tests provider (5-6 commits)
- **Jour 2** : oauth_session + endpoints + tests + reaper (4-5 commits)
- **Jour 3** : frontend (helper + composant wizard + i18n + page) + doc admin (3-4 commits)

Validation à chaque jour via `./scripts/run-test.sh` + relecture des diffs.

## Conventions de commit

- `feat(gdrive-db):` — migrations 107, 108
- `feat(gdrive-provider):` — provider Python, gdrive_client, factory
- `feat(gdrive-oauth):` — service, endpoints, audit log, reaper
- `feat(gdrive-ui):` — schémas, adminApi, helpers, composants, i18n, page
- `docs(gdrive):` — guide admin
- `chore(gdrive):` — Dockerfile + pyproject deps

## Prochaine étape

Plan d'implémentation TDD détaillé via la skill `superpowers:writing-plans`, qui découpera ces 12-15 commits en tâches red/green/refactor exécutables une par une.
