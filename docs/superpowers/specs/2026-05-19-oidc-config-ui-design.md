# UI de paramétrage Keycloak/OIDC — Design

**Date** : 2026-05-19
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Permettre à l'admin de **paramétrer Keycloak via une page UI** (au lieu d'éditer les env vars + redémarrer le backend). L'infrastructure OIDC (login/callback, mapping de rôles, persistence `user_identities`) est déjà en place — ce chantier ajoute uniquement la couche de configuration persistante en DB + l'écran d'administration.

Le **login local reste le bootstrap** et n'est pas remplacé : il sert à se connecter avant d'avoir configuré Keycloak, et à se rabattre en cas de panne Keycloak.

## Contexte

### Ce qui existe déjà (audit code)

**Backend** (`backend/src/agflow/api/admin/auth.py`) :
- `GET /admin/auth/mode` → `{mode: "local" | "keycloak"}` basé sur `settings.auth_mode`
- `GET /admin/auth/oidc/login` : initie le flow OAuth (state CSRF en mémoire + redirect Keycloak `/protocol/openid-connect/auth`)
- `GET /admin/auth/oidc/callback` : token exchange + userinfo + extraction du rôle depuis `resource_access.{client_id}.roles` → mapping `admin`/`operator`/`viewer` → upsert `users` + `user_identities` → JWT app → redirect `/login?token=...`

**Config** (`backend/src/agflow/config.py`) :
- 5 env vars : `auth_mode`, `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `keycloak_client_secret`
- Property `keycloak_base` (concatène URL + realm)

**Frontend** (`frontend/src/pages/LoginPage.tsx`) :
- Fetch `/admin/auth/mode` au montage → bascule entre form local et bouton SSO

### Ce qui manque

La config Keycloak n'est lisible/modifiable que via env vars + redémarrage. Pas d'UI. Cette spec couvre le gap.

## Décisions structurantes (figées en brainstorming)

| # | Axe | Décision | Rationale |
|---|---|---|---|
| 1 | Stockage `client_secret` | **Harpocrate vault** (ref `${vault://...}` en DB) | Cohérent avec tous les autres secrets app (hmac_keys, infra, remote_backup_connections). Rotation simple via UI Harpocrate. |
| 2 | Transition env vars → DB | **Drop net** des env vars (suppression de `config.py`) | L'admin sauvegarde ses identifiants en externe avant migration, démarre en `mode=local`, re-saisit via UI. Pas de double source de vérité. |
| 3 | Bouton « Tester » | **.well-known + token client_credentials** | Diagnostic précis (URL OK ? realm OK ? credentials OK ?). ~2-3s wall. |
| 4 | Save | **Direct, sans pré-requérir test réussi** | L'admin peut sauver une conf partielle (ex: secret à compléter plus tard, ou pendant que Keycloak est down pour maintenance). Test = bouton séparé. |
| 5 | Modèle DB | **Singleton `auth_config`** (PK fixe `id=1`) | Même pattern que `pitr_config`, `git_sync_config`. Suffisant : un seul IdP cible pour V1. |
| 6 | Lecture par `auth.py` | **DB lue à chaque login** (pas de cache) | ~1ms latence par OIDC login (rare). Simple, toujours frais après update UI. |
| 7 | Découpe code | **Module dédié `auth_config_service.py` + extension `auth.py`** | SRP respecté, fichier `auth.py` reste sous 300 lignes. |

## Architecture d'ensemble

```
┌── Settings page (/settings) ─────────────────────────────────┐
│  [Coffres Harpocrate] [Git Sync] [Authentification] ← NEW    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ Mode d'authentification :                              │  │
│  │   ◉ Local seulement   ◯ Local + Keycloak SSO          │  │
│  │                                                        │  │
│  │ (si keycloak sélectionné, champs visibles ↓)           │  │
│  │ URL Keycloak    [ https://keycloak.yoops.org    ]      │  │
│  │ Realm           [ yoops                          ]     │  │
│  │ Client ID       [ agflow-docker                  ]     │  │
│  │ Client Secret   [ ●●●●●●●●●●● (vide=garder)      ]    │  │
│  │ Coffre cible    [ default ▼ ]  (où stocker le secret)  │  │
│  │                                                        │  │
│  │ [ Tester la connexion ]  [ Enregistrer ]               │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘

         ▲                                         ▲
         │ PUT /api/admin/auth-config              │ POST /api/admin/auth-config/test
         │ {mode, url, realm, client_id,           │ → {ok: bool, step, detail,
         │  client_secret?, vault_name}            │     discovery_ok, token_ok}
         ▼                                         ▼

┌── Backend ──────────────────────────────────────────────────┐
│  api/admin/auth_config.py  (NEW)                            │
│    GET  /api/admin/auth-config                              │
│    PUT  /api/admin/auth-config                              │
│    POST /api/admin/auth-config/test                         │
│                                                             │
│  services/auth_config_service.py  (NEW)                     │
│    get_config()         → AuthConfigOut (sans secret)       │
│    get_config_internal()→ AuthConfigInternal (avec ref)     │
│    update_config(...)   → AuthConfigOut                     │
│    test_connection(...) → AuthTestResult                    │
│                                                             │
│  api/admin/auth.py  (MODIFIÉ)                               │
│    /oidc/login    : lit auth_config_service.get_config_internal()│
│    /oidc/callback : idem                                    │
│    /mode          : idem                                    │
│  config.py        (NETTOYÉ : retrait des 5 env vars Keycloak)│
└─────────────────────────────────────────────────────────────┘

         ▲                                         ▲
         │ SELECT/UPDATE                           │ vault_client.set/get
         │ auth_config row id=1                    │ ref = "${vault://<name>:auth/keycloak/client_secret}"
         ▼                                         ▼

┌── Postgres ────────────┐  ┌── Harpocrate ──────────────────┐
│ Table auth_config      │  │ <vault>/auth/keycloak/client_secret =│
│  (singleton, id=1)     │  │  "actual-secret-value"         │
└────────────────────────┘  └────────────────────────────────┘
```

**Composants ajoutés** :
- 1 table singleton `auth_config`
- 1 service Python (~140 LoC)
- 1 schemas Pydantic (~50 LoC)
- 3 endpoints REST
- 1 onglet « Authentification » dans `/settings`
- API client + hook React Query + composant `AuthTab` (~200 LoC)
- ~25 clés i18n FR/EN

**Composants modifiés** :
- `api/admin/auth.py` : lit la DB au lieu de `get_settings()`
- `config.py` : retrait des 5 attributs Keycloak + property `keycloak_base`
- `.env.example` : retrait des 5 lignes Keycloak

## Modèle de données

### Migration 113 — `backend/migrations/113_auth_config.sql`

```sql
-- 113_auth_config.sql — Configuration d'authentification (singleton)

CREATE TABLE auth_config (
    id                          int PRIMARY KEY CHECK (id = 1),
    mode                        text NOT NULL DEFAULT 'local'
                                CHECK (mode IN ('local', 'keycloak')),
    keycloak_url                text NOT NULL DEFAULT '',
    keycloak_realm              text NOT NULL DEFAULT '',
    keycloak_client_id          text NOT NULL DEFAULT '',
    keycloak_client_secret_ref  text NOT NULL DEFAULT '',
    vault_name                  text NOT NULL DEFAULT 'default',
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    updated_by_user_id          uuid REFERENCES users(id) ON DELETE SET NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_auth_config_updated_at') THEN
        CREATE TRIGGER trg_auth_config_updated_at
            BEFORE UPDATE ON auth_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

INSERT INTO auth_config (id, mode) VALUES (1, 'local') ON CONFLICT (id) DO NOTHING;
```

### Notes

- **Singleton via `CHECK (id = 1)`** : pattern existant (`pitr_config`, `git_sync_config`).
- **Mode binaire `local` vs `keycloak`** : `keycloak` ne désactive PAS le login local — il l'expose juste derrière un lien fallback (comportement déjà codé dans LoginPage).
- **`keycloak_client_secret_ref`** : on stocke uniquement la ref Harpocrate (`${vault://<name>:auth/keycloak/client_secret}`), pas la valeur.
- **`vault_name`** : ref texte vers `harpocrate_vaults.name` (pas un FK strict — robustesse au rename/delete coffre).
- **`updated_by_user_id`** : audit ; `ON DELETE SET NULL` préserve l'historique.

### Cleanup associé (pas de migration SQL)

| Fichier | Action |
|---|---|
| `backend/src/agflow/config.py` | Retirer `auth_mode`, `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `keycloak_client_secret`, property `keycloak_base` |
| `.env.example` | Retirer les 5 lignes correspondantes |
| Tests | Adapter les fixtures qui posaient ces env vars |

## API REST

Router `backend/src/agflow/api/admin/auth_config.py`, préfixe `/api/admin/auth-config`, `require_admin` global.

| Méthode | Path | Action | Codes |
|---|---|---|---|
| GET | `/auth-config` | lit la config (sans révéler le secret) | 401/403 |
| PUT | `/auth-config` | met à jour (secret optionnel) | 422, 404 vault |
| POST | `/auth-config/test` | teste la connexion sans persister | 200 toujours, payload détaille |

### Schémas Pydantic — `backend/src/agflow/schemas/auth_config.py`

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthConfigOut(BaseModel):
    mode: Literal["local", "keycloak"]
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    has_secret: bool                            # True si keycloak_client_secret_ref non vide
    vault_name: str
    updated_at: datetime
    updated_by_user_id: UUID | None


class AuthConfigUpdate(BaseModel):
    mode: Literal["local", "keycloak"] | None = None
    keycloak_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None
    keycloak_client_secret: str | None = None  # vide/None = ne pas modifier
    vault_name: str | None = None


class AuthTestRequest(BaseModel):
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str | None = None  # vide = utiliser le secret actuel via vault
    vault_name: str | None = None


class AuthTestResult(BaseModel):
    ok: bool
    step: Literal["discovery", "token", "done"]
    detail: str
    discovery_ok: bool
    token_ok: bool
```

### Validation

- **URL** : commence par `http://` ou `https://`, sinon 422
- **Realm + client_id** : non vides si `mode=keycloak`, sinon 422
- **`vault_name`** : doit exister dans `harpocrate_vaults`, sinon 404
- **`mode=local`** : autorisé avec champs Keycloak vides

### Sémantique des 3 endpoints

**GET `/auth-config`** : Retourne `AuthConfigOut` ; le secret_ref n'est JAMAIS exposé (juste `has_secret: bool`).

**PUT `/auth-config`** :
1. Valide payload
2. Si `keycloak_client_secret` (clair) fourni → push via `vault_client.set_secret(vault_name, "auth/keycloak/client_secret", value)` → stocke la ref dans la colonne
3. UPDATE row singleton
4. Retourne `AuthConfigOut` rafraîchi

**POST `/auth-config/test`** :
1. Si `keycloak_client_secret` vide dans payload → lit le secret actuel via Harpocrate (ref depuis DB)
2. Step 1 : `GET ${url}/realms/${realm}/.well-known/openid-configuration` (timeout 5s)
3. Step 2 : `POST ${url}/realms/${realm}/protocol/openid-connect/token` avec `grant_type=client_credentials` (timeout 5s)
4. Retourne `AuthTestResult` (toujours HTTP 200, statut dans le payload)

## Services backend

### `auth_config_service.py` (~140 lignes)

API publique :

```python
async def get_config() -> AuthConfigOut
async def get_config_internal() -> AuthConfigInternal   # avec ref, usage interne
async def update_config(payload: AuthConfigUpdate, *, actor_user_id: UUID | None) -> AuthConfigOut
async def test_connection(payload: AuthTestRequest) -> AuthTestResult
```

Exceptions :
- `InvalidUrlError(ValueError)` → 422 dans le router
- `VaultNameUnknownError(LookupError)` → 404 dans le router (à ne pas confondre avec `vault_client.VaultNotFoundError` qui signale un coffre absent côté SDK)

Constantes :
- `CLIENT_SECRET_PATH = "auth/keycloak/client_secret"` — chemin standard dans Harpocrate

**`update_config` flow** :
1. Valide URL si fournie
2. Valide `vault_name` existe (via `harpocrate_vaults_service.get_by_name`) — sinon `VaultNameUnknownError`
3. Si `keycloak_client_secret` (clair) fourni → upsert dans Harpocrate :
   - Try `vault_client.update_secret(CLIENT_SECRET_PATH, value, vault_name=vault_name)`
   - On `VaultHttpError(404)` → fallback `vault_client.create_secret(CLIENT_SECRET_PATH, value, description="Keycloak OIDC client_secret", vault_name=vault_name)`
   - Compose la nouvelle ref via `vault_client.build_ref(vault_name, CLIENT_SECRET_PATH)`
4. UPDATE conditionnel champ par champ (SETs construits dynamiquement)
5. Log structuré : `log.info("auth_config.updated", mode=..., keycloak_url=..., actor_user_id=...)` — **JAMAIS** le secret

**`test_connection` flow** :
1. Si secret pas dans payload → résoudre via `vault_client.resolve_ref(ref_de_la_DB)`
2. Si pas de secret nulle part → retourne `AuthTestResult(ok=False, step=discovery, ...)`
3. Step 1 (discovery) via `httpx.AsyncClient` timeout 5s → si HTTP != 200 ou exception → retourne échec
4. Step 2 (token) idem → si HTTP != 200 ou exception → retourne échec
5. Sinon `AuthTestResult(ok=True, step=done, ...)`

### Refactor `api/admin/auth.py`

Les 3 endpoints OIDC existants doivent lire la DB au lieu de `get_settings()` :

```python
# Avant
@router.get("/mode")
async def auth_mode():
    settings = get_settings()
    return {"mode": settings.auth_mode}

# Après
@router.get("/mode")
async def auth_mode():
    cfg = await auth_config_service.get_config_internal()
    return {"mode": cfg.mode}
```

Idem pour `oidc_login` (lit `cfg.keycloak_url`, `cfg.keycloak_client_id`) et `oidc_callback` (lit `cfg.keycloak_client_secret_ref` → résout via `vault_client.resolve_ref()` pour obtenir la valeur du secret au moment de l'appel à Keycloak).

### Cleanup `config.py`

Retirer les 5 attributs + la property. Plus aucune référence à `get_settings()` pour Keycloak côté `auth.py`.

## Frontend

### Onglet « Authentification » dans `/settings`

```
┌── Onglet Authentification ─────────────────────────────────┐
│                                                            │
│  Mode d'authentification                                   │
│  ◉ Local seulement                                         │
│  ◯ Local + Keycloak SSO                                    │
│                                                            │
│  ─── Identifiants Keycloak ─── (grisé si mode=local) ───   │
│                                                            │
│  URL Keycloak       [ https://keycloak.yoops.org      ]    │
│  Realm              [ yoops                            ]   │
│  Client ID          [ agflow-docker                    ]   │
│  Client Secret      [ ●●●●●●●●●●●● (vide = conserver) ]   │
│                     ⓘ Stocké chiffré dans Harpocrate       │
│  Coffre Harpocrate  [ default ▼ ]                          │
│                                                            │
│  [ Tester la connexion ]                  [ Enregistrer ]  │
│                                                            │
│  ─── Résultat du test (zone vide par défaut) ─────────     │
│  ✓ Discovery OK                                            │
│  ✓ client_credentials grant OK                             │
│  → Connexion validée                                       │
└────────────────────────────────────────────────────────────┘
```

### Fichiers

| Fichier | Type | Responsabilité |
|---|---|---|
| `frontend/src/lib/authConfigApi.ts` | Créé | 3 fonctions REST + types |
| `frontend/src/hooks/useAuthConfig.ts` | Créé | React Query (query + 2 mutations) |
| `frontend/src/components/settings/AuthTab.tsx` | Créé | Composant onglet (~200 LoC) |
| `frontend/src/pages/SettingsPage.tsx` | Modifié | Ajout `<TabsTrigger value="auth">` + `<TabsContent>` |
| `frontend/src/i18n/fr.json` | Modifié | ~25 clés sous `settings.auth.*` |
| `frontend/src/i18n/en.json` | Modifié | mêmes clés EN |

### API client `authConfigApi.ts`

```typescript
import { api } from "./api";

export type AuthMode = "local" | "keycloak";

export interface AuthConfig {
  mode: AuthMode;
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  has_secret: boolean;
  vault_name: string;
  updated_at: string;
  updated_by_user_id: string | null;
}

export interface AuthConfigUpdate {
  mode?: AuthMode;
  keycloak_url?: string;
  keycloak_realm?: string;
  keycloak_client_id?: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestRequest {
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestResult {
  ok: boolean;
  step: "discovery" | "token" | "done";
  detail: string;
  discovery_ok: boolean;
  token_ok: boolean;
}

export const authConfigApi = {
  getConfig: async (): Promise<AuthConfig> =>
    (await api.get<AuthConfig>("/admin/auth-config")).data,
  updateConfig: async (payload: AuthConfigUpdate): Promise<AuthConfig> =>
    (await api.put<AuthConfig>("/admin/auth-config", payload)).data,
  testConnection: async (payload: AuthTestRequest): Promise<AuthTestResult> =>
    (await api.post<AuthTestResult>("/admin/auth-config/test", payload)).data,
};
```

### Hook `useAuthConfig.ts`

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { type AuthConfig, type AuthConfigUpdate, type AuthTestRequest, authConfigApi } from "@/lib/authConfigApi";

const AUTH_KEY = ["auth-config"] as const;

export function useAuthConfig() {
  const qc = useQueryClient();
  const query = useQuery<AuthConfig>({
    queryKey: AUTH_KEY,
    queryFn: () => authConfigApi.getConfig(),
  });
  const updateMutation = useMutation({
    mutationFn: (payload: AuthConfigUpdate) => authConfigApi.updateConfig(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: AUTH_KEY }),
  });
  const testMutation = useMutation({
    mutationFn: (payload: AuthTestRequest) => authConfigApi.testConnection(payload),
  });
  return { ...query, update: updateMutation, test: testMutation };
}
```

### Composant `AuthTab.tsx` (~200 lignes)

Form contrôlé :
- **RadioGroup mode** (local / keycloak)
- **4 inputs Keycloak** désactivés si `mode === 'local'` (grisés, pas hidden)
- **Input password client_secret** : placeholder `secret_keep` si `has_secret`, sinon `secret_required`. Vide à la soumission = ne pas modifier
- **Select `vault_name`** : utilise le hook `useHarpocrateVaults` existant
- **Bouton « Tester »** : envoie le contenu du form (sans persister) → affiche `AuthTestResult` (check ✓ / cross ✗ sur les 2 étapes + detail). Disabled si `mode === 'local'`
- **Bouton « Enregistrer »** : mutation update ; disabled pendant pending
- Toast `sonner` sur succès save / échec
- Le champ secret se vide automatiquement après save réussi (sécurité — ne pas garder en mémoire React)

### LoginPage : aucune modification

`/login` lit déjà `/admin/auth/mode` via axios et bascule entre form local et bouton SSO. Aucun changement nécessaire — l'endpoint `/mode` lira désormais la DB via le refactor de `auth.py`.

### i18n — ~25 clés sous `settings.auth.*`

```json
{
  "settings": {
    "tabs": { "auth": "Authentification" },
    "auth": {
      "title": "Authentification",
      "subtitle": "Configurer le mode de connexion (local et/ou Keycloak SSO)",
      "mode_label": "Mode d'authentification",
      "mode_local": "Local seulement",
      "mode_keycloak": "Local + Keycloak SSO",
      "keycloak_section": "Identifiants Keycloak",
      "keycloak_url": "URL Keycloak",
      "keycloak_realm": "Realm",
      "keycloak_client_id": "Client ID",
      "keycloak_client_secret": "Client Secret",
      "secret_keep": "Laisser vide pour conserver le secret actuel",
      "secret_required": "Coller le secret du client",
      "secret_hint_vault": "Stocké chiffré dans Harpocrate",
      "vault_name": "Coffre Harpocrate",
      "test_button": "Tester la connexion",
      "save_button": "Enregistrer",
      "test_result_title": "Résultat du test",
      "test_discovery_ok": "Discovery OK",
      "test_discovery_ko": "Discovery échoué",
      "test_token_ok": "client_credentials grant OK",
      "test_token_ko": "client_credentials échoué",
      "test_done": "Connexion validée",
      "toast_saved": "Configuration enregistrée",
      "toast_save_error": "Erreur lors de l'enregistrement"
    }
  }
}
```

Versions EN équivalentes.

## Tests

### Backend (~25 tests Python)

| Fichier | Tests |
|---|---|
| `tests/services/test_auth_config_service.py` | `get_config` singleton, `update_config` change mode, URL invalide → InvalidUrlError, vault inconnu → VaultNotFoundError, secret poussé dans Harpocrate, ref bien formée, `has_secret` reflète présence |
| `tests/services/test_auth_config_test_connection.py` | `test_connection` happy (discovery+token OK), discovery fail, token fail (HTTP 401), secret pris depuis vault si pas dans payload |
| `tests/api/test_admin_auth_config.py` | GET (admin OK, viewer 403, secret jamais exposé), PUT (admin OK, viewer 403, 422, 404 vault), POST /test (200 même si fail, payload détaille) |
| `tests/api/test_admin_auth_oidc_uses_db.py` | `/mode` lit la DB, `/oidc/login` lit la DB, `/oidc/callback` lit la DB |
| `tests/db/test_migration_113_auth_config.py` | Table existe, singleton seedé, CHECK (id=1) rejette id=2, CHECK mode rejette `'invalid'`, trigger `set_updated_at` fonctionne |

### Frontend (~8 tests Vitest)

| Fichier | Tests |
|---|---|
| `frontend/src/hooks/__tests__/useAuthConfig.test.ts` | Query fetch, mutations invalidation |
| `frontend/src/components/settings/__tests__/AuthTab.test.tsx` | Form rendering, champs grisés si mode=local, bouton Tester désactivé si mode=local, Save appelle update avec bons params, secret vide après save réussi, résultat test affiche check/cross |

### E2E

Pas d'extension de `run-test.sh` requise pour V1. Validation manuelle :
1. Login local OK
2. Page Settings > Authentification accessible
3. Bouton Tester → résultat affiché correctement
4. Save → re-fetch → champs persistent
5. Refresh `/login` → mode appliqué

## Découpage en phases

| Phase | Périmètre | Effort |
|---|---|---|
| **P1 — DB + service backend** | Migration 113 + schemas + `auth_config_service.py` + tests | 1-2j |
| **P2 — API REST + refactor auth.py** | 3 endpoints + refactor 3 endpoints OIDC + nettoyage `config.py` + tests | 1-2j |
| **P3 — Frontend** | API client + hook + AuthTab + intégration SettingsPage + i18n + tests | 1-2j |
| **P4 — Cleanup + validation** | `.env.example`, commit final, smoke manuel | 0.5j |

**Total : 3.5-6.5 jours wall** (~1 semaine réaliste).

## Risques résiduels

| Risque | Mitigation |
|---|---|
| Coffre Harpocrate non configuré au moment du PUT | Validation `vault_name` AVANT push → 404 explicite si absent |
| Secret perdu si coffre Harpocrate reset | By-design ; admin doit re-saisir. V2 : warning UI si ref pointe vers vault inexistant |
| Refactor `auth.py` casse OIDC en cours | State CSRF en mémoire, court-vivant ; déploiement coupe les flows mais c'est rare |
| Migration + drop net = perte credentials | Admin sauvegarde en externe avant migration (décision figée) ; bootstrap via login local toujours OK |
| Secret leaké dans logs structlog | Service ne log JAMAIS la valeur. Vérification en code review. |

## Critères d'acceptation V1

- [ ] Table `auth_config` créée, singleton seedé, CHECK `id=1` testée
- [ ] GET `/auth-config` retourne `has_secret: bool`, JAMAIS la valeur ni la ref
- [ ] PUT `/auth-config` : `mode=local` OK avec champs vides ; `mode=keycloak` + URL invalide → 422 ; vault inconnu → 404
- [ ] PUT pousse le secret dans Harpocrate quand fourni en clair
- [ ] POST `/auth-config/test` : `ok=true` happy ; `ok=false` avec step + detail lisible sinon
- [ ] `/admin/auth/mode`, `/oidc/login`, `/oidc/callback` lisent la DB
- [ ] LoginPage bascule local↔keycloak après save (au refresh)
- [ ] `config.py` ne contient plus aucun attribut Keycloak ; `.env.example` nettoyé
- [ ] ~25 tests Python verts + ~8 Vitest verts
- [ ] Lint clean (ruff + tsc + ESLint)

## Out-of-scope V1 (différé V2)

- ❌ Logout côté Keycloak (revocation session SSO)
- ❌ Refresh token côté app
- ❌ Multi-IdP (Google OAuth + Keycloak en parallèle visibles UI)
- ❌ Rotation automatique du `client_secret`
- ❌ UI mapping configurable des rôles Keycloak → rôles app
- ❌ Détection runtime de coffre absent + warning UI
- ❌ Audit log historique complet (juste `updated_at` + `updated_by_user_id` pour V1)

## Conventions de commit

- `feat(auth-db):` — migration 113
- `feat(auth-services):` — service Python + schemas
- `feat(auth-api):` — 3 endpoints REST + refactor auth.py
- `feat(auth-ui):` — frontend (api client, hook, AuthTab, i18n)
- `chore(auth):` — cleanup config.py + .env.example
- `test(auth):` — tests dédiés
- `docs(auth):` — spec + plan

## Prochaine étape

Plan d'implémentation TDD détaillé via la skill `superpowers:writing-plans`, qui découpera les 4 phases en tâches red/green/refactor exécutables une par une.
