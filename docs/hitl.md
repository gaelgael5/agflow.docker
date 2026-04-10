# HITL Console — port 8090

Console web pour la validation humaine (Human-In-The-Loop).

## Authentification

| Mode | `auth_type` | `password_hash` | Flux |
|---|---|---|---|
| **Local** (email/password) | `local` | bcrypt hash | Inscription → rôle `undefined` → validation admin → accès |
| **Google OAuth** | `google` | `NULL` | Sign-in Google → rôle `undefined` → validation admin → accès |

## Rôles utilisateur

| Rôle | Accès |
|---|---|
| `undefined` | Aucun accès — en attente de validation |
| `member` | Accès aux équipes assignées — répondre aux questions |
| `admin` | Accès complet — toutes les équipes + gestion membres |

## Google OAuth

Config via `config/hitl.json` :

```json
{
  "auth": { "jwt_expire_hours": 24, "allow_registration": true, "default_role": "undefined" },
  "google_oauth": {
    "enabled": true,
    "client_id": "123456789-xxxxxxxx.apps.googleusercontent.com",
    "client_secret_env": "GOOGLE_CLIENT_SECRET",
    "allowed_domains": ["company.com"]
  }
}
```

Flux : Google Identity Services → ID token → POST /api/auth/google → vérif token + audience + domaine → rôle `undefined` → validation admin.

## Endpoints

| Endpoint | Méthode | Auth | Rôle |
|---|---|---|---|
| `/api/auth/login` | POST | Non | Login email/password |
| `/api/auth/register` | POST | Non | Inscription (rôle `undefined`) |
| `/api/auth/google` | POST | Non | Login Google (ID token) |
| `/api/auth/google/client-id` | GET | Non | Retourne le Client ID |
| `/api/auth/me` | GET | JWT | Profil utilisateur courant |
| `/api/teams` | GET | JWT | Équipes de l'utilisateur |
| `/api/teams/{id}/questions` | GET | JWT | Questions HITL (inbox) |
| `/api/questions/{id}/answer` | POST | JWT | Répondre / approuver / rejeter |
| `/api/teams/{id}/members` | GET/POST | JWT | Gestion membres |
| `/api/teams/{id}/ws` | WS | JWT (query) | Notifications temps réel |

## Base de données

```sql
password_hash TEXT           -- NULL pour les comptes Google
role          TEXT DEFAULT 'undefined'  -- 'undefined' | 'member' | 'admin'
auth_type     TEXT DEFAULT 'local'      -- 'local' | 'google'
```
