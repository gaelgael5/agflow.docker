# Spécification des recettes produits — agflow Product Registry (M7)

> Ce document est la référence complète pour écrire des recettes YAML de produits
> pour le Product Registry d'agflow.docker. À utiliser comme contexte pour demander
> la génération de nouvelles recettes.

---

## 1. Contexte

agflow.docker est une plateforme d'instanciation d'agents IA CLI dans des containers Docker. Le **Product Registry (M7)** catalogue les produits logiciels (wiki, tasks, code, design, infra) que les agents peuvent utiliser. Chaque produit est décrit par une **recette YAML** qui contient tout ce qu'il faut pour le déployer, le connecter aux agents, et générer la documentation API.

### Flux complet

```
Catalogue (recettes YAML)
    ↓ l'admin choisit un produit
Composition (instance virtuelle attachée à un projet)
    ↓ le système résout variables + génère secrets
Génération (docker-compose.yml + .env)
    ↓ l'admin déploie sur une machine
Activation (l'admin saisit l'URL publique)
    ↓ le système auto-crée : MCP binding + contrat OpenAPI + RAG
Agents (héritent automatiquement du contexte produit)
```

### Produits existants dans le catalogue

| id | Catégorie | Type | Connectors | API |
|---|---|---|---|---|
| outline | wiki | self-hosted (4 services + rag-worker) | mcp-outline (uvx, communautaire) | ✅ runtime |
| github | code | SaaS config_only | @github/github-mcp-server (npx, officiel) | ✅ statique |
| gitlab | code | SaaS config_only | @modelcontextprotocol/server-gitlab (npx, officiel) | ✅ statique |
| jira | tasks | SaaS config_only | @anthropics/mcp-server-atlassian (npx, officiel) | ✅ statique |
| postgres-inline | infra | config_only | @benborge/mcp-postgres (npx, officiel) | ❌ |
| openproject | tasks | self-hosted (2 services) | openproject-mcp (uvx, communautaire) + officiel enterprise /mcp | ✅ runtime |
| plane | tasks | self-hosted (6 services) | plane-mcp-server (uvx, officiel) + remote /mcp | ✅ runtime |
| taiga | tasks | self-hosted (6 services) | taiga-mcp-server (npx, communautaire) + pytaiga-mcp (uvx) | ❌ pas d'OpenAPI |
| shared/pgvector | infra | shared dependency | ❌ (mcp-search à construire) | ❌ |

---

## 2. Structure d'une recette

```yaml
# En-tête (obligatoire)
id: string                  # Identifiant unique, snake_case
display_name: string        # Nom affiché dans l'UI
description: string         # Description courte
category: string            # wiki | tasks | code | design | infra
tags: [string]              # Tags libres
min_ram_mb: integer          # RAM minimum (0 pour SaaS)
config_only: boolean         # true = SaaS, false = self-hosted

# Blocs fonctionnels
variables: [...]             # Paramètres configurables par l'admin
secrets_required: [...]      # Secrets nécessaires
services: [...]              # Containers Docker (absent si config_only: true)
connectors: [...]            # MCP servers pour le pilotage par agents
api: {...}                   # Contrat OpenAPI pour les scripts curl
shared_dependencies: [...]   # Dépendances partagées (ex: pgvector)
exposed: {...}               # Valeurs publiées (shared dependencies uniquement)
post_activation: [...]       # Instructions manuelles après premier démarrage
```

---

## 3. Les trois familles de variables

### 3.1 Variables utilisateur — `{{ nom }}`

Paramètres saisis par l'admin à la composition. Définies dans le bloc `variables`.
Résolues à la **génération** des artefacts.

```yaml
variables:
  - name: domain
    description: Domaine d'accès public
    type: string               # string | integer | boolean
    required: true             # true → pas de default, mettre un example
    example: docs.pickup.io    # affiché si required
    default: "valeur"          # obligatoire si required: false
```

**Règles :**
- Jamais de valeur sensible dans une variable. Utiliser un secret.
- `required: true` → `example` obligatoire, pas de `default`
- `required: false` → `default` obligatoire

### 3.2 Secrets — `${NOM}`

Valeurs sensibles. Définis dans le bloc `secrets_required`.
Restent en `${NOM}` dans le docker-compose.yml, résolus au **runtime** par Docker depuis le `.env`.

```yaml
secrets_required:
  - name: OUTLINE_DB_PASSWORD
    description: Mot de passe PostgreSQL
    generate: random_base64(24)  # ou random_hex(N) ou null
```

**Méthodes `generate` :**

| Méthode | Produit | Usage |
|---|---|---|
| `random_hex(N)` | N caractères hex (a-f0-9) | Clés de chiffrement (SECRET_KEY) |
| `random_base64(N)` | N octets aléatoires en base64 | Mots de passe (DB, admin) |
| `null` | Pas d'auto-génération | Tokens API à créer manuellement |

**Convention de nommage :** `{PRODUIT}_{FONCTION}` (ex: `OUTLINE_DB_PASSWORD`, `PLANE_SECRET_KEY`)

### 3.3 Variables système — `{{ system }}`

Résolues automatiquement par le moteur. Jamais définies dans `variables` ni `secrets_required`.

| Variable | Résolu quand | Description |
|---|---|---|
| `{{ instance_id }}` | Génération | UUID de l'instance M7 |
| `{{ service_url }}` | Activation | URL publique saisie par l'admin |
| `{{ services.<id>.host }}` | Génération | Hostname réseau Docker du service frère |
| `{{ shared.<id>.<key> }}` | Génération | Valeur exposée par une shared dependency |

**Règles critiques :**
- `{{ service_url }}` → uniquement dans `connectors` et `api`, **jamais** dans `services.env_template`
- `{{ instance_id }}` → uniquement dans `services.env_template`
- `{{ shared.<id>.<key> }}` → la dépendance doit être dans `shared_dependencies`, erreur si non instanciée

---

## 4. Bloc `services`

Containers Docker à déployer. **Absent si `config_only: true`.**

```yaml
services:
  - id: app                          # Identifiant unique, snake_case
    image: org/image:tag             # Image Docker
    ports: [3000]                    # Ports exposés
    optional: false                  # true = peut être omis
    description: "..."               # Recommandé si optional: true
    requires_services: [db, redis]   # Dépendances → depends_on dans le compose
    requires_shared: [pgvector]      # Shared dependencies requises
    command: "cmd args"              # Override commande Docker (optionnel)
    env_template:                    # Variables d'env avec substitutions
      VAR: "valeur ou {{ var }} ou ${SECRET}"
    volumes:
      - name: volume-name
        mount: /path/in/container
    healthcheck:
      type: http                    # http | command
      path: /health                 # si type: http
      port: 3000                    # si type: http
      command: "cmd"                # si type: command
```

**Convention de nommage des services :** `app`, `db`, `redis`, `worker`, `rag-worker`

**Images agflow personnalisées :** hébergées sur `ghcr.io/ag-flow/registry/{nom}:latest`
Exemple : `ghcr.io/ag-flow/registry/rag-worker-outline:latest`

---

## 5. Bloc `connectors`

MCP servers que les agents utiliseront pour piloter le produit. C'est la "télécommande" du produit.

```yaml
connectors:
  - name: string                    # Nom descriptif
    description: string             # Ce que le MCP permet
    package: string                 # Package npm ou pypi
    runtime: string                 # npx | uvx | null (si intégré au produit)
    transport: string               # stdio | streamable-http | sse
    url: string                     # URL du MCP (si transport HTTP)
    env:                            # Variables d'env pour le MCP
      VAR: "{{ service_url }}"      # Seuls {{ service_url }} et ${SECRET} autorisés
    status: string                  # officiel | communautaire | officiel-enterprise
    note: string                    # Note complémentaire (optionnel)
```

**Règles :**
- **Au moins un connecteur par recette.** Pas de produit sans MCP fonctionnel.
- Dans `env`, uniquement `{{ service_url }}` et `${SECRET}`. Pas de `{{ services.<id>.host }}`.
- Le premier connecteur est le recommandé.

**Runtimes :**
- `npx` → package npm, lancé via npx dans le container agent
- `uvx` → package PyPI, lancé via uvx dans le container agent
- `null` → MCP intégré au produit (endpoint HTTP natif)

**Statuts :**
- `officiel` → maintenu par l'éditeur du produit
- `communautaire` → maintenu par la communauté
- `officiel-enterprise` → éditeur, licence payante requise

### Connecteurs existants vérifiés

| Produit | Package | Runtime | Variables d'env |
|---|---|---|---|
| Outline | `mcp-outline` | uvx | `OUTLINE_API_KEY`, `OUTLINE_API_URL` |
| GitHub | `@github/github-mcp-server` | npx | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| GitLab | `@modelcontextprotocol/server-gitlab` | npx | `GITLAB_PERSONAL_ACCESS_TOKEN`, `GITLAB_API_URL` |
| Jira | `@anthropics/mcp-server-atlassian` | npx | `JIRA_URL`, `JIRA_API_TOKEN`, `JIRA_USERNAME` |
| PostgreSQL | `@benborge/mcp-postgres` | npx | `POSTGRES_CONNECTION_STRING` |
| OpenProject | `openproject-mcp` | uvx | `OPENPROJECT_URL`, `OPENPROJECT_API_KEY` |
| Plane | `plane-mcp-server` | uvx | `PLANE_API_KEY`, `PLANE_WORKSPACE_SLUG`, `PLANE_BASE_URL` |
| Taiga (Node) | `taiga-mcp-server` | npx | `TAIGA_API_URL`, `TAIGA_USERNAME`, `TAIGA_PASSWORD` |
| Taiga (Python) | `pytaiga-mcp` | uvx | `TAIGA_API_URL`, `TAIGA_USERNAME`, `TAIGA_PASSWORD` |

---

## 6. Bloc `api`

Contrat OpenAPI du produit. Utilisé pour **générer automatiquement les scripts curl** (`.sh` par tag + index `.md`) injectés dans le workspace des agents.

L'agent a donc **deux moyens** de piloter le produit : le MCP (interactif, 90% des cas) et les scripts curl (documentation complète de toute l'API, filet de sécurité).

```yaml
api:
  source: string              # runtime | static
  url: string                 # URL du fichier OpenAPI
  base_url: string            # Base URL des appels API
  auth_header: string         # Header d'auth (Authorization, PRIVATE-TOKEN, X-Api-Key)
  auth_prefix: string         # Préfixe (Bearer, Basic, "")
  auth_secret_ref: string     # Référence au secret ${NOM}
```

**Bloc absent** si le produit n'a pas de spec OpenAPI (Taiga, Postgres). Les agents utilisent uniquement le MCP.

### Source `runtime`
Le contrat est hébergé par le produit. Fetché **à l'activation**.

```yaml
api:
  source: runtime
  url: "http://{{ services.app.host }}:3000/api/openapi.json"   # réseau Docker interne
  base_url: "{{ service_url }}/api"                              # URL publique
```

### Source `static`
Le contrat est sur internet, indépendant de l'instance.

```yaml
api:
  source: static
  url: "https://raw.githubusercontent.com/.../api.github.com.json"
  base_url: "https://api.github.com"
```

### Headers d'auth générés dans les scripts curl

| auth_header | auth_prefix | Résultat |
|---|---|---|
| `Authorization` | `Bearer` | `Authorization: Bearer $TOKEN` |
| `Authorization` | `Basic` | `Authorization: Basic $TOKEN` |
| `PRIVATE-TOKEN` | `""` | `PRIVATE-TOKEN: $TOKEN` |
| `X-Api-Key` | `""` | `X-Api-Key: $TOKEN` |

### Ce qui se passe à l'activation

```
1. Le système lit le bloc api de la recette
2. Résout l'URL ({{ services.app.host }} → hostname Docker)
3. Fetch le contrat OpenAPI
4. Parse les tags
5. Pour chaque tag → génère un répertoire .sh + index .md
6. Crée un agent_api_contract en base (managed_by_instance = UUID instance)
7. À la prochaine génération agent, les scripts sont dans le workspace
```

---

## 7. Bloc `shared_dependencies`

Dépendances partagées entre produits d'un même projet (ex: pgvector partagé entre tous les workers RAG).

```yaml
shared_dependencies:
  - pgvector
```

Chaque dépendance a sa propre recette dans `data/products/shared/`. Le générateur vérifie qu'elle est instanciée dans le projet. Ses valeurs `exposed` sont accessibles via `{{ shared.<id>.<key> }}`.

---

## 8. Bloc `exposed`

**Shared dependencies uniquement.** Valeurs publiées pour les consommateurs.

```yaml
exposed:
  url: "postgres://vectors:${PGVECTOR_PASSWORD}@{{ services.db.host }}:5432/vectors"
```

Accessible dans les recettes consommatrices via `{{ shared.pgvector.url }}`.

---

## 9. Bloc `post_activation`

Instructions manuelles après premier démarrage. Pour les secrets `generate: null` qui nécessitent une action humaine.

```yaml
post_activation:
  - step: "Connectez-vous à l'instance via le bouton {{ oidc_display_name }}"
  - step: "Allez dans Settings > API > Create token"
  - step: "Copiez le token comme valeur de OUTLINE_API_TOKEN"
```

---

## 10. Checklist de validation

Avant de livrer une recette :

- [ ] En-tête complet : id, display_name, description, category, tags, min_ram_mb, config_only
- [ ] Au moins un connecteur avec status vérifié et package réel (pas de placeholder)
- [ ] Chaque `{{ variable }}` dans un env_template a une entrée dans `variables`
- [ ] Chaque `${SECRET}` dans un env_template a une entrée dans `secrets_required`
- [ ] Chaque `{{ services.<id>.host }}` référence un id de service existant
- [ ] Chaque `{{ shared.<id>.* }}` a la dépendance dans `shared_dependencies`
- [ ] `{{ service_url }}` uniquement dans `connectors` et `api`
- [ ] `{{ instance_id }}` uniquement dans `services.env_template`
- [ ] Secrets `generate: null` → description explique comment obtenir la valeur
- [ ] Services `optional: true` si liés à des secrets non disponibles au premier démarrage
- [ ] `api` bloc → auth_header/prefix/secret_ref cohérents avec la doc officielle du produit
- [ ] `post_activation` présent si secrets `generate: null` nécessitent une action manuelle
- [ ] `config_only: true` → pas de bloc `services`
- [ ] `config_only: false` → au moins un service avec `ports`
- [ ] Pas de variables dupliquées dans le bloc `variables`
- [ ] Le package MCP existe réellement (vérifier npm/pypi)
- [ ] Les noms de variables d'env du MCP correspondent à la doc du package

---

## 11. Exemples de référence

### Produit self-hosted complet → `outline.yaml`
4 services (app, db, redis, rag-worker optionnel), auth OIDC, shared dependency pgvector, MCP communautaire uvx, contrat OpenAPI runtime, post_activation.

### Produit SaaS → `github.yaml`
config_only, MCP officiel npx, contrat OpenAPI statique, un secret manuel.

### Shared dependency → `shared/pgvector.yaml`
Bloc `exposed` qui publie l'URL de connexion.

### Produit sans API → `taiga.yaml`
Pas de bloc `api`, deux MCP communautaires (npx + uvx), agents pilotent uniquement via MCP.

---

## 12. Pour demander une nouvelle recette

Fournir au minimum :
1. **Le produit** : nom, URL officielle, SaaS ou self-hosted
2. **La catégorie** : wiki, tasks, code, design, infra
3. **Le MCP** : un lien vers un MCP server existant (npm, pypi, GitHub)
4. **L'API** : URL de la spec OpenAPI si elle existe

Le reste (variables, secrets, services, auth) sera déduit de la documentation officielle du produit.
