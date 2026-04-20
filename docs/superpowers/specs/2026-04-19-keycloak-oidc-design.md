# Intégration Keycloak OIDC — Design Spec

> **Date** : 2026-04-19
> **Statut** : Validé
> **Scope** : Authentification SSO via Keycloak OpenID Connect, rôles, migration réversible

## Contexte

agflow.docker utilise aujourd'hui un JWT HS256 signé en interne avec login email/password + Google OAuth partiel. L'objectif est de basculer sur Keycloak (`security.yoops.org`, realm `yoops`) comme fournisseur d'identité principal via OpenID Connect, tout en gardant un fallback local paramétrable.

## Architecture

Le backend agflow devient un **client OIDC confidentiel** dans Keycloak (realm `yoops`). Le flow est Authorization Code standard :

1. Frontend redirige vers Keycloak
2. L'utilisateur s'authentifie (email/password Keycloak ou Google via Keycloak)
3. Keycloak redirige vers `https://docker-agflow.yoops.org/api/admin/auth/oidc/callback` avec un code
4. Le backend échange le code contre un access token + refresh token Keycloak
5. Le backend émet son propre JWT agflow enrichi du rôle (`admin`/`operator`/`viewer`)
6. Le frontend stocke le JWT agflow dans localStorage (pas de changement)

### Pourquoi un JWT agflow et pas directement le token Keycloak ?

- Pas de dépendance runtime à Keycloak pour chaque requête API (pas de validation RS256 + JWKS à chaque call)
- Les API keys (`agfd_...`) restent compatibles sans changement
- Le fallback local fonctionne avec le même mécanisme
- Migration réversible : on switch un paramètre, pas l'architecture

## Configuration (.env)

```env
# Mode auth : "keycloak" ou "local"
AUTH_MODE=keycloak

# Keycloak OIDC (ignoré si AUTH_MODE=local)
KEYCLOAK_URL=https://security.yoops.org
KEYCLOAK_REALM=yoops
KEYCLOAK_CLIENT_ID=agflow-docker
KEYCLOAK_CLIENT_SECRET=<secret>

# Local fallback (toujours disponible même quand AUTH_MODE=keycloak)
ADMIN_EMAIL=gaelgael5@gmail.com
ADMIN_PASSWORD_HASH=...
```

## Rôles (Keycloak client roles)

Trois rôles définis comme **client roles** dans Keycloak (spécifiques au client `agflow-docker`) :

| Rôle | Accès |
|------|-------|
| `admin` | Tout (secrets, users, infra, agents, config) |
| `operator` | Agents, sessions, infra, MCP, builds — pas secrets globaux ni gestion users |
| `viewer` | Lecture seule partout |

Les rôles sont extraits du token Keycloak (`resource_access.agflow-docker.roles`) et stockés dans le JWT agflow sous le claim `role`.

## Flow détaillé

```
[Login Page]
    │
    ├─ Bouton "Se connecter" ──→ GET /api/admin/auth/oidc/login
    │                                │
    │                          302 → Keycloak authorize URL
    │                                │
    │                          User s'authentifie sur Keycloak
    │                                │
    │                          302 → /api/admin/auth/oidc/callback?code=...&state=...
    │                                │
    │                          Backend : exchange code → Keycloak token
    │                          Backend : extract email + roles from userinfo/token
    │                          Backend : upsert user in DB (provider=keycloak, subject=sub)
    │                          Backend : encode JWT agflow {sub: email, role: "admin", iat, exp}
    │                                │
    │                          302 → /login?token=JWT
    │
    └─ Lien "Connexion locale" ──→ Formulaire email/password (comme aujourd'hui)
```

## Backend — Fichiers à modifier/créer

### `config.py` — Nouvelles settings

```python
auth_mode: str = "local"  # "keycloak" ou "local"
keycloak_url: str = ""
keycloak_realm: str = ""
keycloak_client_id: str = ""
keycloak_client_secret: str = ""
```

Propriété calculée :
```python
@property
def keycloak_base(self) -> str:
    return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
```

### `auth/jwt.py` — Ajout claim `role`

Le JWT agflow passe de :
```json
{"sub": "user@example.com", "iat": ..., "exp": ...}
```
à :
```json
{"sub": "user@example.com", "role": "admin", "iat": ..., "exp": ...}
```

- `encode_token(email, role="admin")` — ajoute le claim `role`
- `decode_token(token)` — retourne le payload avec `role`
- Rétrocompatibilité : si `role` absent dans un vieux token → default `"admin"`

### `auth/dependencies.py` — Nouvelles dépendances

```python
async def require_admin(creds) -> str:
    # Vérifie role == "admin"

async def require_operator(creds) -> str:
    # Vérifie role in ("admin", "operator")

async def require_viewer(creds) -> str:
    # Vérifie role in ("admin", "operator", "viewer")
```

`require_auth()` (API publique) reste inchangé — accepte JWT + API keys.

### `api/admin/auth.py` — Nouveaux endpoints OIDC

```
GET  /api/admin/auth/oidc/login     → 302 vers Keycloak authorize
GET  /api/admin/auth/oidc/callback  → échange code, upsert user, 302 vers /login?token=JWT
GET  /api/admin/auth/mode           → {"mode": "keycloak"|"local"} (public, pas d'auth)
```

L'endpoint `/mode` permet au frontend de savoir quel bouton afficher sans configuration côté client.

### Routers existants — Ajustement des dépendances

| Module | Dépendance actuelle | Nouvelle dépendance |
|--------|--------------------|--------------------|
| Secrets globaux | `require_admin` | `require_admin` (inchangé) |
| Users | `require_admin` | `require_admin` (inchangé) |
| Dockerfiles, Roles, Agents | `require_admin` | `require_operator` |
| MCP, Skills, Products, Infra | `require_admin` | `require_operator` |
| Sessions, builds (lecture) | `require_admin` | `require_viewer` |
| API publique | `require_auth` | `require_auth` (inchangé) |

## Frontend — Fichiers à modifier

### `LoginPage.tsx`

- Appel `GET /api/admin/auth/mode` au chargement
- Si `mode === "keycloak"` : bouton principal "Se connecter" redirige vers `/api/admin/auth/oidc/login`
- Lien discret "Connexion locale" en bas → affiche le formulaire email/password actuel
- Gestion du callback : si `?token=` dans l'URL → stocker dans localStorage et rediriger

### `useAuth.ts`

- Extraire le `role` du JWT décodé (base64 payload)
- Exposer `role` dans le contexte auth
- Helper : `isAdmin()`, `isOperator()`, `isViewer()`

### `Sidebar.tsx`

- Masquer les entrées selon le rôle :
  - `viewer` : pas de boutons d'action (create, delete), lecture seule
  - `operator` : pas de Secrets globaux, pas de Users
  - `admin` : tout visible

### `api.ts`

- Pas de changement (Bearer token agflow identique)

## Ce qui ne change PAS

- API keys (`agfd_...`) : inchangées, gérées localement
- WebSocket auth (`?token=`) : inchangé
- `require_auth()` : accepte toujours JWT + API key
- localStorage `agflow_token` : même clé, même format
- Tout le flow post-login (requêtes API, intercepteurs 401)

## Keycloak — Configuration requise

1. Créer le client `agflow-docker` dans le realm `yoops`
   - Client type : Confidential
   - Valid redirect URIs : `https://docker-agflow.yoops.org/api/admin/auth/oidc/callback`
   - Web origins : `https://docker-agflow.yoops.org`
2. Créer 3 client roles : `admin`, `operator`, `viewer`
3. Assigner le rôle `admin` à l'utilisateur principal
4. Récupérer le client secret → `KEYCLOAK_CLIENT_SECRET` dans `.env`

## Migration

### Activation Keycloak
1. Créer le client dans Keycloak
2. Ajouter les variables dans `.env`
3. Mettre `AUTH_MODE=keycloak`
4. Redéployer

### Retour au mode local
1. Mettre `AUTH_MODE=local`
2. Redéployer
3. Le login email/password fonctionne immédiatement
