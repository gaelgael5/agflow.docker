# Spec — Gestion utilisateurs & API Keys

> **Date** : 2026-04-12
> **Scope** : authentification, users CRUD, API keys CRUD, middleware auth, rate limiting
> **Hors scope** : Google OAuth (prérequis infra non résolus), endpoints publics `/api/v1/*` (spec séparée)

---

## 1. Vue d'ensemble

### 1.1 Objectifs

Mettre en place le socle d'authentification multi-utilisateur d'agflow.docker :

1. **Table `users`** avec cycle de vie (pending → active → disabled)
2. **Gestion des utilisateurs** par l'admin (approbation, attribution de rôle, désactivation)
3. **Table `api_keys`** avec tokens auto-validants (HMAC checksum + expiration embarquée)
4. **Middleware FastAPI** — `require_api_key(*scopes)` avec validation 3 niveaux (checksum → DB → rate limit)
5. **Rate limiting** par clé via Redis (compteur INCR + TTL 60s)
6. **UI admin** — page de gestion des API keys (CRUD + révocation)
7. **UI admin** — page de gestion des utilisateurs (liste, approbation, rôle, désactivation)

### 1.2 Auth — deux modes coexistants

| Mode | Utilisé par | Header | Préfixe token |
|---|---|---|---|
| **JWT** (session) | UI admin (navigateur) | `Authorization: Bearer eyJ...` | `eyJ` (standard JWT) |
| **API key** (machine) | Scripts, CI/CD, API externe | `Authorization: Bearer agfd_...` | `agfd_` |

Le backend distingue les deux par le préfixe `agfd_`. Si le token commence par `agfd_` → pipeline API key. Sinon → pipeline JWT (existant).

### 1.3 Dépendances techniques

- **PostgreSQL** : tables `users` + `api_keys` (migrations SQL)
- **Redis** : compteurs rate limit (clé `ratelimit:agfd_{prefix}`, TTL 60s)
- **bcrypt** : hash des tokens API key (déjà utilisé pour le password admin)
- **HMAC-SHA256** : checksum embarqué dans le token (module `hmac` stdlib)
- **Config** : nouvelle env var `API_KEY_SALT` (32+ chars random, dans `.env`)

---

## 2. Modèle de données

### 2.1 Table `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    avatar_url  TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('admin', 'user')),
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id),
    last_login  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
```

**Champs** :

| Colonne | Type | Description |
|---|---|---|
| `id` | UUID | PK, auto-généré |
| `email` | TEXT | Email unique, sert de login pour l'admin legacy |
| `name` | TEXT | Nom affiché |
| `avatar_url` | TEXT | URL photo provider (vide si pas d'OAuth) |
| `role` | TEXT | `admin` ou `user` — l'admin choisit à la main |
| `scopes` | TEXT[] | Scopes assignés par l'admin. Ex: `{roles:read, roles:write, agents:read, agents:run}`. L'admin a implicitement `{*}` (pas besoin de lister). Un user ne peut créer des API keys qu'avec un sous-ensemble de SES scopes. |
| `status` | TEXT | `pending` (inscrit, non approuvé), `active` (approuvé), `disabled` (désactivé) |
| `created_at` | TIMESTAMPTZ | Date d'inscription |
| `approved_at` | TIMESTAMPTZ | Date d'approbation par l'admin |
| `approved_by` | UUID FK → users | Qui a approuvé |
| `last_login` | TIMESTAMPTZ | Dernier login réussi |

La table `users` ne contient **aucun champ lié à un provider OAuth spécifique**. Le lien se fait via la table `user_identities` ci-dessous.

### 2.2 Table `user_identities`

```sql
CREATE TABLE IF NOT EXISTS user_identities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    email       TEXT,
    name        TEXT,
    avatar_url  TEXT,
    raw_claims  JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_lookup ON user_identities(provider, subject);
```

**Champs** :

| Colonne | Type | Description |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK → users | Le user agflow auquel cette identité est rattachée. `ON DELETE CASCADE` |
| `provider` | TEXT | Identifiant du provider : `google`, `facebook`, `github`, `microsoft`, etc. |
| `subject` | TEXT | ID unique chez le provider (Google `sub`, GitHub `id`, etc.). Immutable |
| `email` | TEXT | Email retourné par le provider (peut différer de `users.email`) |
| `name` | TEXT | Nom retourné par le provider |
| `avatar_url` | TEXT | URL avatar du provider |
| `raw_claims` | JSONB | Payload OpenID / OAuth complet (pour debug et audit) |
| `created_at` | TIMESTAMPTZ | Date de liaison |

**Contrainte** : `UNIQUE (provider, subject)` — un même couple provider+subject ne peut être lié qu'à un seul user.

**Un user peut avoir N identities** (ex: Google + GitHub liés au même compte).

**Flow OAuth générique** (implémentation future, hors scope de cette spec) :
1. Frontend → `GET /api/auth/{provider}/url` → backend retourne l'URL de consentement
2. Redirect navigateur vers le provider → l'utilisateur consent
3. Provider redirige vers `/api/auth/{provider}/callback?code=xxx`
4. Backend échange le `code` contre un `access_token` → lit email, name, avatar, subject
5. Lookup `user_identities(provider, subject)` :
   - **Trouvé** → charge le user existant
   - **Pas trouvé** → lookup `users(email)` (match par email cross-provider) :
     - Si user existe → lie la nouvelle identité (`INSERT user_identities`)
     - Si pas de user → crée un nouveau user `status: pending` + lie l'identité
6. Si `status: active` → émet un JWT agflow → retour au frontend
7. Si `status: pending` → retourne 403 "Compte en attente de validation"

**L'admin actuel (login email/password)** reste fonctionnel en parallèle comme fallback.

**Cycle de vie** :

```
Inscription (Google OAuth ou création admin)
    │
    ▼
 pending ───── admin approve ────▶ active ───── admin disable ────▶ disabled
    │                                 │                                │
    └── admin refuse ──▶ (DELETE)     └── admin re-enable ◀───────────┘
```

**Admin initial** : à la première migration, un user admin est seedé à partir des env vars existantes (`ADMIN_EMAIL`). Son `google_id` est NULL, son status est `active`, son role est `admin`.

### 2.3 Table `api_keys`

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL UNIQUE,              -- 12 chars hex, lookup index
    key_hash        TEXT NOT NULL,                     -- bcrypt hash du token complet
    scopes          TEXT[] NOT NULL DEFAULT '{}',      -- ex: {dockerfiles:read, containers:run}
    rate_limit      INT NOT NULL DEFAULT 120,          -- requêtes par minute
    expires_at      TIMESTAMPTZ,                       -- NULL = pas d'expiration
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner_id);
```

**Champs** :

| Colonne | Type | Description |
|---|---|---|
| `id` | UUID | PK |
| `owner_id` | UUID FK → users | Propriétaire de la clé. `ON DELETE CASCADE` — si le user est supprimé, ses clés aussi |
| `name` | TEXT | Libellé choisi par l'utilisateur (ex: "CI pipeline", "dev test") |
| `prefix` | TEXT UNIQUE | 12 chars hex (identifiant public de la clé, visible dans les listings) |
| `key_hash` | TEXT | bcrypt hash du token complet `agfd_...` |
| `scopes` | TEXT[] | Liste des permissions accordées. `{"*"}` = accès total |
| `rate_limit` | INT | Requêtes autorisées par minute (défaut 120) |
| `expires_at` | TIMESTAMPTZ | Redondant avec l'expiration dans le token. Sert à l'affichage UI |
| `revoked` | BOOLEAN | Soft delete — la clé existe en base mais est refusée |
| `created_at` | TIMESTAMPTZ | Date de création |
| `last_used_at` | TIMESTAMPTZ | Mis à jour à chaque appel API authentifié |

---

## 3. Format du token API key

### 3.1 Structure

```
agfd_<prefix:12><expiry:8><random:20><hmac:8>
│    │           │         │          │
│    │           │         │          └─ 8 chars hex : HMAC-SHA256(API_KEY_SALT, prefix+expiry+random)[:8]
│    │           │         └─ 20 chars hex : entropie aléatoire (80 bits)
│    │           └─ 8 chars hex : timestamp Unix d'expiration en hexa
│    └─ 12 chars hex : identifiant DB (index UNIQUE, en clair en base)
└─ préfixe fixe "agfd_"

Longueur totale : 5 + 48 = 53 caractères
```

**Décomposition avec sous-totaux** :

| Segment | Taille | Contenu | Stocké en DB ? |
|---|---|---|---|
| `agfd_` | 5 chars | Préfixe fixe | Non (implicite) |
| prefix | 12 hex chars | Identifiant de lookup | ✅ en clair (`prefix` column) |
| expiry | 8 hex chars | Timestamp Unix 32 bits | ✅ redondant (`expires_at` column) |
| random | 20 hex chars | Entropie | ❌ jamais stocké |
| hmac | 8 hex chars | Checksum HMAC-SHA256 | ❌ recalculé à la volée |
| **TOTAL** | **53 chars** | | Hash bcrypt stocké (`key_hash`) |

### 3.2 Encodage de l'expiration

| Option UI | Hex encodé | Exemple timestamp |
|---|---|---|
| 3 mois | `{ts:08x}` | `67a1b2c0` |
| 6 mois | `{ts:08x}` | `694d5e80` |
| 9 mois | `{ts:08x}` | `6af90a40` |
| 12 mois | `{ts:08x}` | `6ca4b600` |
| Pas d'expiration | `ffffffff` | (year 2106) |

### 3.3 HMAC — paramètres

| Paramètre | Valeur |
|---|---|
| Algorithme | HMAC-SHA256 |
| Clé | `API_KEY_SALT` (env var, 32+ chars, généré une fois) |
| Message | `prefix + expiry_hex + random_hex` (40 chars) |
| Troncature | 8 premiers chars hex du digest (32 bits) |
| Comparaison | `hmac.compare_digest()` (timing-safe) |

### 3.4 Génération (Python)

```python
import hmac
import hashlib
import secrets
from datetime import datetime

import bcrypt


def generate_api_key(
    salt: str,
    expires_at: datetime | None,
) -> tuple[str, str, str]:
    """Generate a self-validating API key.

    Returns:
        full_key:  "agfd_..." — shown to user ONCE
        prefix:    12 hex chars — stored in DB for lookup
        key_hash:  bcrypt hash — stored in DB for verification
    """
    prefix = secrets.token_hex(6)          # 12 hex chars
    if expires_at is None:
        expiry_hex = "ffffffff"
    else:
        expiry_hex = f"{int(expires_at.timestamp()):08x}"
    random_part = secrets.token_hex(10)    # 20 hex chars
    body = prefix + expiry_hex + random_part
    checksum = hmac.new(
        salt.encode(), body.encode(), hashlib.sha256
    ).hexdigest()[:8]
    full_key = f"agfd_{body}{checksum}"
    key_hash = bcrypt.hashpw(
        full_key.encode(), bcrypt.gensalt()
    ).decode()
    return full_key, prefix, key_hash
```

### 3.5 Parsing (Python)

```python
import re

_KEY_RE = re.compile(
    r"^agfd_"
    r"(?P<prefix>[0-9a-f]{12})"
    r"(?P<expiry>[0-9a-f]{8})"
    r"(?P<random>[0-9a-f]{20})"
    r"(?P<hmac>[0-9a-f]{8})$"
)

class ParsedKey:
    prefix: str      # 12 hex
    expiry_ts: int   # unix timestamp (0xFFFFFFFF = no expiry)
    random: str      # 20 hex
    hmac_value: str  # 8 hex
    body: str        # prefix + expiry + random (pour recalcul HMAC)

def parse_api_key(raw: str) -> ParsedKey | None:
    m = _KEY_RE.match(raw.strip().lower())
    if not m:
        return None
    return ParsedKey(
        prefix=m.group("prefix"),
        expiry_ts=int(m.group("expiry"), 16),
        random=m.group("random"),
        hmac_value=m.group("hmac"),
        body=m.group("prefix") + m.group("expiry") + m.group("random"),
    )
```

---

## 4. Middleware d'authentification

### 4.1 `require_api_key(*required_scopes)`

Dependency FastAPI injectable. Validation en 3 niveaux, du plus cheap au plus cher :

```python
def require_api_key(*required_scopes: str):
    """FastAPI Depends() factory. Returns the api_key DB row on success."""

    async def _dep(
        creds: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    ) -> dict:
        if creds is None:
            raise HTTPException(401, _err("missing_token", "Authorization header required"))
        token = creds.credentials

        # ─── LEVEL 1 : structure + HMAC + expiry (O(1), zero I/O) ───
        parsed = parse_api_key(token)
        if parsed is None:
            raise HTTPException(401, _err("invalid_format", "Token must start with agfd_ and be 53 chars"))

        expected_hmac = hmac.new(
            settings.api_key_salt.encode(),
            parsed.body.encode(),
            hashlib.sha256,
        ).hexdigest()[:8]
        if not hmac.compare_digest(expected_hmac, parsed.hmac_value):
            raise HTTPException(401, _err("invalid_checksum", "Token checksum failed"))

        if parsed.expiry_ts != 0xFFFFFFFF:
            if parsed.expiry_ts < int(time.time()):
                raise HTTPException(401, _err("expired", "API key has expired"))

        # ─── LEVEL 2 : DB lookup + bcrypt (~100ms) ───
        row = await fetch_one(
            "SELECT * FROM api_keys WHERE prefix = $1", parsed.prefix
        )
        if row is None or row["revoked"]:
            raise HTTPException(401, _err("revoked_or_unknown", "API key not found or revoked"))

        if not bcrypt.checkpw(token.encode(), row["key_hash"].encode()):
            raise HTTPException(401, _err("hash_mismatch", "Invalid API key"))

        # Scope check
        granted = set(row["scopes"])
        if "*" not in granted:
            for scope in required_scopes:
                if scope not in granted:
                    raise HTTPException(
                        403,
                        _err("missing_scope", f"This key lacks the '{scope}' scope"),
                    )

        # ─── LEVEL 3 : rate limit (1 Redis INCR) ───
        await _check_rate_limit(parsed.prefix, row["rate_limit"])

        # Update last_used_at (fire-and-forget, don't block the response)
        asyncio.create_task(_update_last_used(row["id"]))

        return row

    return Depends(_dep)
```

### 4.2 Format d'erreur unifié (API publique)

```python
def _err(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
```

Réponse HTTP :
```json
{
  "error": {
    "code": "missing_scope",
    "message": "This key lacks the 'dockerfiles:write' scope"
  }
}
```

### 4.3 Rate limiting (Redis)

```python
async def _check_rate_limit(prefix: str, limit: int) -> None:
    redis = get_redis()
    key = f"ratelimit:agfd_{prefix}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)  # TTL 60 secondes
    if current > limit:
        raise HTTPException(
            429,
            _err("rate_limited", f"Rate limit exceeded ({limit}/min)"),
            headers={
                "Retry-After": str(await redis.ttl(key)),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + await redis.ttl(key)),
            },
        )
```

### 4.4 Headers de rate limit sur chaque réponse

Ajoutés via un middleware FastAPI global pour les routes `/api/v1/*` :

```http
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 117
X-RateLimit-Reset: 1720000060
X-API-Key-Prefix: a1b2c3d4e5f6
```

### 4.5 Distinction JWT vs API key

```python
# Dans un dependency "universel" qui accepte les deux :
async def require_auth(creds = Depends(HTTPBearer())):
    token = creds.credentials
    if token.startswith("agfd_"):
        return await _validate_api_key(token)
    else:
        return await _validate_jwt(token)  # existant
```

---

## 5. Catalogue des scopes & modèle de permissions

### 5.1 Catalogue de tous les scopes existants

| Scope | Description |
|---|---|
| `*` | Super-scope, accès total (réservé aux admins) |
| `secrets:read` | Lire les secrets (noms, pas les valeurs) |
| `secrets:write` | Créer/modifier/supprimer des secrets |
| `dockerfiles:read` | Lister, détailler les dockerfiles |
| `dockerfiles:write` | Créer, modifier, importer des dockerfiles |
| `dockerfiles:delete` | Supprimer un dockerfile |
| `dockerfiles:build` | Compiler une image |
| `dockerfiles.files:read` | Lire le contenu des fichiers |
| `dockerfiles.files:write` | Créer/modifier des fichiers |
| `dockerfiles.files:delete` | Supprimer des fichiers |
| `dockerfiles.params:read` | Lire Dockerfile.json parsé |
| `dockerfiles.params:write` | Modifier Dockerfile.json |
| `discovery:read` | Lister les services de découverte |
| `discovery:write` | CRUD services de découverte |
| `service_types:read` | Lister les types de services |
| `service_types:write` | CRUD types de services |
| `users:manage` | CRUD utilisateurs, approbation, rôle, scopes |
| `roles:read` | Lister/détailler les rôles |
| `roles:write` | Créer/modifier des rôles |
| `roles:delete` | Supprimer des rôles |
| `catalogs:read` | Lister MCP + Skills |
| `catalogs:write` | Ajouter/supprimer MCP + Skills |
| `agents:read` | Lister/détailler les agents composés |
| `agents:write` | Créer/modifier des agents |
| `agents:delete` | Supprimer des agents |
| `agents:run` | Lancer un agent composé |
| `containers:read` | Lister les containers actifs |
| `containers:run` | Lancer un container |
| `containers:stop` | Arrêter un container |
| `containers.logs:read` | Lire les logs d'un container |
| `containers.chat:write` | Envoyer une tâche chat |
| `keys:manage` | CRUD ses propres API keys |

### 5.2 Modèle de permissions — admin assigne, user hérite

Le modèle n'est PAS une matrice statique rôle → scopes. Les scopes sont **assignés par l'admin à chaque user individuellement**.

**Règles** :

1. **Admin** (`role = admin`) : a implicitement le scope `*` (tout). Pas besoin de lister ses scopes explicitement. Peut créer des API keys avec n'importe quel scope.

2. **User** (`role = user`) : n'a accès qu'aux scopes que l'admin lui a **explicitement assignés** dans `users.scopes[]`. Exemple : `{roles:read, roles:write, agents:read, agents:run, containers:read, containers:run, keys:manage}`.

3. **API key** : un user ne peut créer une API key qu'avec des scopes **⊆ ses propres scopes**. Si le user a `{agents:read, agents:run}`, il ne peut pas créer une clé avec `agents:write`.

4. **`keys:manage`** : toujours implicitement accordé à tout user `active` (il peut gérer ses propres clés même si l'admin ne l'a pas listé explicitement).

**Validation à la création d'une API key** :

```python
ALL_SCOPES: set[str] = { ... }  # catalogue complet ci-dessus

def validate_key_scopes(
    user_role: str,
    user_scopes: list[str],
    requested_scopes: list[str],
) -> list[str]:
    """Returns list of rejected scopes (empty = all OK)."""
    # Validate scope names exist
    unknown = [s for s in requested_scopes if s not in ALL_SCOPES and s != "*"]
    if unknown:
        return unknown

    # Admin can request anything
    if user_role == "admin":
        return []

    # User: requested must be a subset of their assigned scopes
    granted = set(user_scopes) | {"keys:manage"}  # keys:manage is always implicit
    return [s for s in requested_scopes if s not in granted]
```

### 5.3 UX admin — assignation des scopes à un user

Dans la page **Utilisateurs**, quand l'admin clique sur un user :
- Section "Permissions" avec des **checkboxes groupées par resource** :

```
☐ Secrets         [☐ read] [☐ write]
☐ Dockerfiles     [☐ read] [☐ write] [☐ delete] [☐ build]
☐ Dockerfiles.files  [☐ read] [☐ write] [☐ delete]
☐ Dockerfiles.params [☐ read] [☐ write]
☐ Discovery       [☐ read] [☐ write]
☐ Service types   [☐ read] [☐ write]
☐ Users           [☐ manage]
───────────────────────────────
☑ Roles           [☑ read] [☑ write] [☐ delete]
☑ Catalogs        [☑ read] [☐ write]
☑ Agents          [☑ read] [☐ write] [☐ delete] [☑ run]
☑ Containers      [☑ read] [☑ run] [☐ stop]
☑ Containers.logs [☑ read]
☑ Containers.chat [☑ write]
☑ Keys            [☑ manage]  ← toujours coché, non décochable
```

Boutons raccourcis :
- **"Profil standard"** : coche les scopes typiques d'un user (roles, catalogs, agents, containers, keys)
- **"Tout cocher"** / **"Tout décocher"**

---

## 6. Endpoints admin — API Keys

### 6.1 Routes

Préfixe : `/api/admin/api-keys`
Auth : JWT admin (`require_admin`)

| Méthode | Route | Description | Body / Params |
|---|---|---|---|
| `POST` | `/api/admin/api-keys` | Créer une clé | `{name, scopes[], rate_limit?, expires_in?}` |
| `GET` | `/api/admin/api-keys` | Lister toutes les clés | — |
| `GET` | `/api/admin/api-keys/{id}` | Détail d'une clé | — |
| `PATCH` | `/api/admin/api-keys/{id}` | Modifier (name, scopes, rate_limit) | `{name?, scopes?[], rate_limit?}` |
| `DELETE` | `/api/admin/api-keys/{id}` | Révoquer | — |

### 6.2 Schémas Pydantic

```python
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)
    rate_limit: int = Field(default=120, ge=1, le=10000)
    expires_in: Literal["3m", "6m", "9m", "12m", "never"] = "12m"

class ApiKeyCreated(BaseModel):
    """Returned ONCE at creation — contains the full token."""
    id: UUID
    name: str
    prefix: str
    full_key: str          # agfd_... — NEVER stored, shown once
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    created_at: datetime

class ApiKeySummary(BaseModel):
    """Returned by list/detail — no full_key."""
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None
    owner_id: UUID | None

class ApiKeyUpdate(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    rate_limit: int | None = Field(default=None, ge=1, le=10000)
```

### 6.3 Endpoint POST — création

```python
@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(payload: ApiKeyCreate) -> ApiKeyCreated:
    # 1. Compute expires_at from expires_in
    expires_at = _compute_expiry(payload.expires_in)

    # 2. Generate token
    full_key, prefix, key_hash = generate_api_key(
        salt=settings.api_key_salt,
        expires_at=expires_at,
    )

    # 3. Insert in DB
    row = await db_insert_api_key(
        name=payload.name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=payload.scopes,
        rate_limit=payload.rate_limit,
        expires_at=expires_at,
        owner_id=None,  # admin legacy, pas de user_id encore
    )

    # 4. Return with full_key (ONCE)
    return ApiKeyCreated(
        id=row["id"],
        name=payload.name,
        prefix=prefix,
        full_key=full_key,    # ← le user doit le copier maintenant
        scopes=payload.scopes,
        rate_limit=payload.rate_limit,
        expires_at=expires_at,
        created_at=row["created_at"],
    )
```

### 6.4 UX frontend — page API Keys

**Emplacement** : nouvelle entrée "API Keys" dans la sidebar admin sous "Plateforme".

**Vue liste** :
- Table : Nom, Préfixe (`agfd_a1b2...`), Scopes (badges), Rate limit, Expire le, Dernière utilisation, Statut (actif/révoqué)
- Bouton "+ Créer une clé" en haut
- Bouton "Révoquer" par ligne (avec confirmation)

**Dialog création** :
- Champ "Nom" (texte libre)
- Champ "Scopes" (checkboxes groupées par resource)
- Champ "Limite req/min" (input numérique, défaut 120)
- Champ "Expiration" (dropdown : 3 mois / 6 mois / 9 mois / 12 mois / Pas d'expiration)
- Bouton "Créer"
- **Après création** : dialog "Token créé" avec le token complet affiché dans un input readonly + bouton Copier. Message d'avertissement : "Ce token ne sera plus jamais affiché. Copie-le maintenant."

**Dialog édition** (PATCH) :
- Modifier nom, scopes, rate limit
- L'expiration et le token ne sont PAS modifiables (il faut révoquer et recréer)

---

## 7. Endpoints admin — Users

### 7.1 Routes

Préfixe : `/api/admin/users`
Auth : JWT admin (`require_admin`)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/api/admin/users` | Lister tous les users (pending en premier) |
| `GET` | `/api/admin/users/{id}` | Détail d'un user |
| `POST` | `/api/admin/users` | Créer un user manuellement (invitation) |
| `PATCH` | `/api/admin/users/{id}` | Modifier role, status |
| `POST` | `/api/admin/users/{id}/approve` | Approuver un user pending |
| `POST` | `/api/admin/users/{id}/disable` | Désactiver un user |
| `POST` | `/api/admin/users/{id}/enable` | Réactiver un user disabled |
| `DELETE` | `/api/admin/users/{id}` | Supprimer un user (cascade ses API keys) |

### 7.2 Schémas Pydantic

```python
class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=200)
    role: Literal["admin", "user"] = "user"
    scopes: list[str] = Field(default_factory=list)   # admin assigne les scopes
    status: Literal["pending", "active"] = "active"   # invitation admin → active directement

class UserSummary(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    scopes: list[str]
    status: str
    created_at: datetime
    approved_at: datetime | None
    last_login: datetime | None
    api_key_count: int  # nombre de clés actives

class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["admin", "user"] | None = None
    scopes: list[str] | None = None                   # admin modifie les scopes
```

### 7.3 UX frontend — page Users

**Emplacement** : nouvelle entrée "Utilisateurs" dans la sidebar admin sous "Plateforme".

**Vue liste** :
- Users pending en haut (fond ambre), puis actifs, puis désactivés (grisés)
- Colonnes : Avatar, Nom, Email, Rôle (badge admin/user), Statut (badge), Clés API actives, Dernière connexion, Actions
- Actions : Approuver (si pending), Désactiver/Réactiver, Changer rôle (dropdown inline), Supprimer

**Admin initial** : à la première migration, l'admin existant (env var `ADMIN_EMAIL`) est seedé comme user `admin` + `active`. Ses API keys (si créées avant la migration) sont rattachées via l'email match.

---

## 8. Configuration backend

### 8.1 Nouvelles env vars

| Variable | Description | Exemple | Obligatoire |
|---|---|---|---|
| `API_KEY_SALT` | Secret HMAC pour checksum token | `a3f8b2c1d4e5...` (32+ hex chars) | ✅ |

### 8.2 Pydantic Settings (config.py)

Ajouts :
```python
api_key_salt: str = Field(min_length=16)
```

### 8.3 Redis — utilisation

Le Redis existant (déjà configuré dans config.py via `redis_url`) est utilisé pour le rate limiting. Pas de nouvelle instance.

Clés Redis créées :
- `ratelimit:agfd_{prefix}` — INT, TTL 60s auto-expire
- Aucune autre donnée persistante dans Redis (tout est en PostgreSQL)

---

## 9. Migrations SQL

### 9.1 Migration 022 — table `users`

```sql
-- 022_users.sql
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    avatar_url  TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('admin', 'user')),
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id),
    last_login  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
```

### 9.2 Migration 023 — table `user_identities`

```sql
-- 023_user_identities.sql
CREATE TABLE IF NOT EXISTS user_identities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    email       TEXT,
    name        TEXT,
    avatar_url  TEXT,
    raw_claims  JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_lookup ON user_identities(provider, subject);
```

### 9.3 Migration 024 — seed admin initial

```sql
-- 024_seed_admin_user.sql
-- Seeds the initial admin user from the legacy ADMIN_EMAIL env var.
-- This migration is handled in Python (needs access to settings) via a
-- post-migration hook in the backend lifespan, not in raw SQL.
```

Note : cette migration est un placeholder. Le seed se fait dans le `lifespan` du backend après les migrations SQL, car il a besoin de lire `settings.admin_email`.

### 9.4 Migration 025 — table `api_keys`

```sql
-- 025_api_keys.sql
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL UNIQUE,
    key_hash        TEXT NOT NULL,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    rate_limit      INT NOT NULL DEFAULT 120,
    expires_at      TIMESTAMPTZ,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner_id);
```

---

## 10. Fichiers à créer / modifier

### 10.1 Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `backend/migrations/022_users.sql` | Table users |
| `backend/migrations/023_user_identities.sql` | Table user_identities (multi-provider OAuth) |
| `backend/migrations/024_seed_admin_user.sql` | Placeholder (seed en Python) |
| `backend/migrations/025_api_keys.sql` | Table api_keys |
| `backend/src/agflow/schemas/user_identities.py` | DTOs Pydantic pour les identités provider |
| `backend/src/agflow/services/user_identities_service.py` | CRUD identities (link/unlink provider) |
| `backend/src/agflow/schemas/users.py` | DTOs Pydantic (UserCreate, UserSummary, UserUpdate) |
| `backend/src/agflow/schemas/api_keys.py` | DTOs Pydantic (ApiKeyCreate, ApiKeyCreated, ApiKeySummary, ApiKeyUpdate) |
| `backend/src/agflow/services/users_service.py` | CRUD users + seed admin |
| `backend/src/agflow/services/api_keys_service.py` | Génération, CRUD, validation |
| `backend/src/agflow/auth/api_key.py` | `parse_api_key()`, `require_api_key()`, rate limiting |
| `backend/src/agflow/api/admin/users.py` | Router admin users |
| `backend/src/agflow/api/admin/api_keys.py` | Router admin API keys |
| `backend/tests/test_api_keys_service.py` | Tests unitaires service |
| `backend/tests/test_api_keys_endpoint.py` | Tests endpoint CRUD + middleware |
| `backend/tests/test_users_service.py` | Tests unitaires users |
| `frontend/src/pages/ApiKeysPage.tsx` | Page admin API keys |
| `frontend/src/pages/UsersPage.tsx` | Page admin Users |
| `frontend/src/hooks/useApiKeys.ts` | React Query hook |
| `frontend/src/hooks/useUsers.ts` | React Query hook |
| `frontend/src/lib/apiKeysApi.ts` | Client API |
| `frontend/src/lib/usersApi.ts` | Client API |

### 10.2 Fichiers modifiés

| Fichier | Modification |
|---|---|
| `backend/src/agflow/config.py` | Ajouter `api_key_salt` |
| `backend/src/agflow/main.py` | Ajouter routers users + api_keys, seed admin dans lifespan |
| `backend/src/agflow/auth/dependencies.py` | Ajouter `require_auth()` qui accepte JWT ou API key |
| `frontend/src/components/layout/Sidebar.tsx` | Ajouter "API Keys" + "Utilisateurs" dans la sidebar |
| `frontend/src/App.tsx` | Ajouter routes `/api-keys` + `/users` |
| `frontend/src/i18n/fr.json` | Clés i18n pour les deux pages |
| `frontend/src/i18n/en.json` | Idem anglais |
| `.env.example` | Ajouter `API_KEY_SALT=` |

---

## 11. Tests

### 11.1 Backend — service `api_keys_service`

| Test | Vérifie |
|---|---|
| `test_generate_key_format` | Le token fait 53 chars, commence par `agfd_`, HMAC valide |
| `test_generate_key_expiry_encoding` | L'expiry hex décode au bon timestamp |
| `test_parse_valid_key` | Parsing correct des 4 segments |
| `test_parse_invalid_key_rejected` | Clé trop courte / mauvais préfixe → None |
| `test_hmac_validation_rejects_tampered` | Modifier 1 char → checksum fail |
| `test_expired_key_rejected` | Clé avec expiry passé → 401 au level 1 |
| `test_create_and_list` | CRUD complet |
| `test_revoke_key` | Clé révoquée → 401 au level 2 |
| `test_scope_check` | Clé sans le scope requis → 403 |
| `test_rate_limit` | Dépasser rate_limit → 429 |
| `test_last_used_updated` | Appel réussi → last_used_at mis à jour |

### 11.2 Backend — service `users_service`

| Test | Vérifie |
|---|---|
| `test_seed_admin` | L'admin initial est créé au démarrage |
| `test_create_user` | Création manuelle par admin |
| `test_approve_user` | pending → active, approved_at rempli |
| `test_disable_user` | active → disabled |
| `test_enable_user` | disabled → active |
| `test_delete_cascades_keys` | Supprimer un user supprime ses API keys |
| `test_user_cannot_exceed_own_scopes` | User avec scopes `{agents:read}` → clé avec `agents:write` refusée |
| `test_keys_manage_always_implicit` | User sans `keys:manage` explicite → peut quand même gérer ses clés |
| `test_admin_can_assign_any_scope` | Admin assigne `dockerfiles:write` à un user → user peut créer une clé avec ce scope |

### 11.3 Frontend

| Test | Vérifie |
|---|---|
| `test_api_keys_page_renders` | La page affiche la liste |
| `test_create_key_shows_token` | Après création, le dialog affiche le token |
| `test_users_page_renders` | La page affiche les users |

---

## 12. Hors scope (à traiter dans des specs futures)

| Sujet | Pourquoi pas maintenant |
|---|---|
| Google OAuth | Prérequis infra non résolus (IP fixe LXC, Cloudflare tunnel, Google Console) |
| Endpoints publics `/api/v1/*` | Spec séparée, dépend de cette spec |
| Audit logging détaillé | Phase ultérieure, pas bloquant pour le MVP |
| Rotation de clé (regen sans révoquer) | Nice-to-have, la révocation + recréation suffit |
| 2FA / MFA | Pas de sens avant Google OAuth |
| Multi-tenant (organisations) | Pas prévu dans le MVP |
