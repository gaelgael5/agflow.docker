# 14 — Contrats API d'agents et fichiers de runtime

Ce fichier complète le module 04 (M4 — composition d'agents) en détaillant deux mécanismes essentiels qui rendent les agents utilement opérationnels au runtime :
1. Les **contrats API** attachés à un agent — décrivent les APIs externes qu'il peut consommer.
2. Les **profils de mission** — sous-ensembles de documents du rôle qu'on applique au runtime.
3. La **génération des fichiers de runtime** — production effective des artefacts chargés par le container de l'agent.

## 1. Contrats API attachés à un agent

### Pourquoi

Un agent IA polyvalent doit pouvoir appeler des APIs externes (GitHub, Slack, JIRA, services internes, etc.) sans avoir codé en dur leurs détails dans son prompt. Les **contrats API** (`agent_api_contracts`) attachent à un agent les **spécifications OpenAPI** des services qu'il peut utiliser, et la plateforme génère pour lui une documentation utilisable à l'intérieur de son container.

Le contrat n'est **pas** un client SDK — c'est une description que l'agent peut lire et qui lui permet de générer ses propres appels HTTP via les MCP tools de type `http_request` ou équivalent.

### Modèle

Une ligne `agent_api_contracts` contient :

| Champ | Rôle |
|---|---|
| `id` | UUID |
| `agent_id` | FK vers l'agent du catalogue |
| `slug` | Identifiant alphanumérique unique par agent |
| `display_name` | Libellé UI |
| `description` | Description courte |
| `source_type` | `upload` / `url` / `manual` |
| `source_url` | URL d'origine si `source_type=url` (rafraîchissable) |
| `spec_content` | Contenu OpenAPI brut (JSON ou YAML) |
| `base_url` | URL de base canonique (déclarative) |
| `runtime_base_url` | URL effective au runtime (peut différer de base_url quand le service tourne dans un container du runtime) |
| `auth_header` | Nom du header d'auth (défaut `Authorization`) |
| `auth_prefix` | Préfixe (défaut `Bearer`) |
| `auth_secret_ref` | Référence Harpocrate vers le secret d'auth |
| `parsed_tags` | JSONB — extraction des tags OpenAPI avec compteur d'opérations |
| `tag_overrides` | JSONB — descriptions custom par slug de tag |
| `managed_by_instance` | FK product_instances, nullable — si le contrat est auto-géré par une instance de produit déployée |
| `output_dir` | Répertoire de sortie dans le workspace de l'agent (défaut `workspace/docs/ctr`) |
| `position` | Ordre d'affichage / d'inclusion |

### Sources

#### Upload

L'admin uploade un fichier OpenAPI (JSON ou YAML) via l'UI. Le contenu est stocké dans `spec_content`. Pas de mise à jour automatique — un nouvel upload écrase.

#### URL

L'admin fournit une URL distante. La plateforme la fetch immédiatement (validation que l'URL répond), parse le contenu, le stocke dans `spec_content` et garde `source_url` pour pouvoir rafraîchir plus tard via `POST /api/admin/agents/{agent_id}/contracts/{contract_id}/refresh`.

#### Manual

L'admin colle directement le contenu OpenAPI dans l'UI. Pas de source remote.

### Preview avant import

Endpoint : `POST /api/admin/agents/{agent_id}/contracts/fetch-spec` avec `{ "url": "…" }` retourne le contenu brut pour preview avant création. Permet à l'opérateur de valider le contenu avant de le sauvegarder.

### Tags et descriptions

Au moment du parsing :
- Le service extrait tous les `tags` OpenAPI avec leur description et le nombre d'opérations couvertes.
- Stocke dans `parsed_tags` : array de `TagSummary` :

```json
[
  { "slug": "repos", "name": "Repositories", "description": "Repo management", "operation_count": 12 },
  { "slug": "issues", "name": "Issues", "description": "Issue tracker", "operation_count": 8 }
]
```

- `tag_overrides` permet à l'admin de **remplacer** la description d'un tag pour la rendre plus utile à l'agent :

```json
{ "repos": "Utilise ces endpoints pour CRUD des repos. Préférer search avant create." }
```

La description finale rendue à l'agent est : `tag_overrides[slug]` si présent, sinon `parsed_tags[i].description`.

### Endpoints CRUD

- `GET /api/admin/agents/{agent_id}/contracts` — lister.
- `POST /api/admin/agents/{agent_id}/contracts` — créer.
- `GET /api/admin/agents/{agent_id}/contracts/{contract_id}` — détail (avec `spec_content` complet).
- `PUT /api/admin/agents/{agent_id}/contracts/{contract_id}` — mise à jour partielle.
- `DELETE /api/admin/agents/{agent_id}/contracts/{contract_id}` — supprimer.
- `POST /api/admin/agents/{agent_id}/contracts/{contract_id}/refresh` — re-fetch depuis `source_url` (préserve `tag_overrides`).
- `PUT /api/admin/agents/{agent_id}/contracts/reorder` — réordonner par array d'IDs.

### Authentification

Chaque contrat porte son couple `auth_header` / `auth_prefix` / `auth_secret_ref`. Au moment du rendu :
- `auth_secret_ref` est résolu via le résolveur unifié (en général une référence `${vault://api:…}`).
- L'agent reçoit dans son `.env` une variable de la forme `<SLUG>_AUTH_TOKEN` (avec slug uppercased) qu'il combine avec `auth_header` + `auth_prefix` pour ses appels.

### Rendu dans le workspace de l'agent

Au moment de `POST /api/admin/agents/{agent_id}/generate`, le service produit dans le workspace de l'agent :

```
<workspace>/<output_dir>/
├── README.md                     # Index des contrats
├── <slug-1>/
│   ├── overview.md               # Description + base_url + auth
│   ├── tags.md                   # Liste des tags avec descriptions (overrides appliqués)
│   └── operations.md             # Liste des opérations par tag, avec curl examples
├── <slug-2>/
│   └── …
└── …
```

L'agent peut lire ces fichiers depuis son prompt initial pour savoir quelles APIs sont à sa disposition.

### Contrats auto-gérés

Quand un product_instance est déployé et que le produit a `has_openapi=true`, la plateforme crée automatiquement un contrat lié à l'agent assistant (M4) avec :
- `source_type=url`, `source_url=<instance.service_url>/openapi.json`.
- `managed_by_instance` pointant sur l'instance.
- `runtime_base_url=<instance.service_url>`.

Quand l'instance est stoppée ou détruite, le contrat auto-géré est désactivé (mais pas supprimé pour conserver l'audit). À la réactivation, il est rafraîchi.

## 2. Profils de mission (`agent_profiles`)

### Pourquoi

Un même agent (par exemple « Claude Code DevOps ») peut être instancié dans des contextes très différents : audit d'une PR, génération de docs, debugging incident. Chaque contexte requiert un **sous-ensemble** des documents du rôle attaché à l'agent.

Les **profils de mission** modélisent ces sous-ensembles : un profil = un nom + une description + une liste de `document_ids` à inclure dans le prompt final.

### Modèle

| Champ | Rôle |
|---|---|
| `id` | UUID |
| `agent_id` | FK vers l'agent |
| `name` | Nom (unique par agent) |
| `description` | Description courte |
| `document_ids` | Array UUID des documents du rôle à inclure |
| `template_slug` | Template Jinja2 dédié à cette mission (optionnel — sinon réutilise celui de l'agent) |
| `template_culture` | Culture du template (optionnel) |
| `output_dir` | Répertoire de sortie pour les fichiers de mission (défaut `workspace/docs/missions`) |

### Création et édition

- `GET /api/admin/agents/{agent_id}/profiles` — lister les profils d'un agent.
- `POST /api/admin/agents/{agent_id}/profiles` — créer.
- `PUT /api/admin/agents/{agent_id}/profiles/{profile_id}` — mettre à jour (nom, description, document_ids, template).
- `DELETE /api/admin/agents/{agent_id}/profiles/{profile_id}` — supprimer.

Conflits :
- `409` si on crée un profil avec un nom déjà pris pour cet agent.
- `404` si le profil ne correspond pas à l'agent.

### Sélection au runtime

Trois mécanismes d'utilisation :

1. **Génération explicite** : `POST /api/admin/agents/{agent_id}/generate?profile_id=…` génère les fichiers de runtime en appliquant le profil sélectionné.
2. **Aperçu** : `GET /api/admin/agents/{agent_id}/config-preview?profile_id=…` retourne le `prompt_md` final tel qu'il sera injecté dans le container.
3. **Instanciation en session** : `POST /sessions/{id}/agents` accepte un champ `mission` libre (string) — si elle correspond au `name` d'un profil de l'agent, le profil correspondant est appliqué automatiquement.

### Effet sur le prompt rendu

Sans profil → le `prompt_md` final concatène l'`identity_md` du rôle + tous les documents de toutes les sections.

Avec profil → l'`identity_md` reste, mais seuls les documents listés dans `document_ids` sont inclus, dans l'ordre `position` original au sein de leurs sections respectives.

Le template Jinja2 utilisé (par défaut celui de l'agent, ou celui spécifié par le profil) reçoit la variable `profile` :

```jinja2
{% if profile %}
# Mission active : {{ profile.name }}
{{ profile.description }}
{% endif %}

# Identité
{{ identity_md }}

# Documents
{% for doc in selected_documents %}
## {{ doc.section.display_name }} — {{ doc.name }}
{{ doc.content_md }}
{% endfor %}
```

### Génération multi-rôles (`AgentGeneration` blocks)

Certains agents nécessitent **plusieurs rôles** (par exemple un agent « assistant projet » qui combine un rôle « code reviewer » et un rôle « tech writer »). La table `agents.generations` permet de déclarer plusieurs blocs de génération, chacun produisant son propre fichier prompt :

```json
[
  {
    "role_id": "code-reviewer",
    "template_slug": "review-prompt",
    "template_culture": "fr",
    "prompt_filename": "review-prompt.md",
    "profiles": [
      { "name": "audit-pr", "documents": ["uuid1", "uuid2"], "template_slug": "audit-template" }
    ]
  },
  {
    "role_id": "tech-writer",
    "template_slug": "writer-prompt",
    "template_culture": "fr",
    "prompt_filename": "writer-prompt.md",
    "profiles": [ ]
  }
]
```

Chaque bloc génère son propre fichier de prompt. L'agent en runtime peut choisir le prompt à activer selon le contexte du work reçu.

## 3. Génération des fichiers de runtime

### Vue d'ensemble

Au moment où on **instancie un agent dans une session** (ou par un appel explicite `POST /api/admin/agents/{id}/generate`), le backend produit dans le **workspace de l'agent** un ensemble de fichiers que le container montera et lira au démarrage.

```
/app/data/agents/<agent_id>/workspace/
├── prompt.md                 # System prompt (rendu Jinja2)
├── config.toml               # MCP config (rendu Jinja2)
├── skills.md                 # Catalogue de skills (rendu Jinja2)
├── .env                      # Variables d'environnement résolues
├── docs/
│   ├── ctr/                  # Contrats API (cf. section 1)
│   └── missions/             # Fichiers de mission si profil appliqué (cf. section 2)
└── …
```

### Étapes de la génération

1. **Résolution des bindings** : pour chaque MCP binding et skill binding de l'agent, charger les définitions du catalogue.
2. **Résolution des secrets** : pour chaque référence dans les configurations, appeler l'`input_resolver` (fail-fast).
3. **Rendu des templates** :
   - `prompt_template_<slug>` → `prompt.md`.
   - `mcp_template_<slug>` → `mcp_config_filename` (typiquement `config.toml`).
   - `skills_template_<slug>` → `skills_config_filename` (typiquement `skills.md`).
4. **Rendu des contrats API** : un sous-répertoire par contrat sous `docs/ctr/`.
5. **Rendu de la mission active** : si `profile_id` fourni, génération des fichiers de mission sous `docs/missions/`.
6. **Génération du `.env`** : assemblage des `env_vars` de l'agent + secrets résolus + variables système (`AGFLOW_SESSION_ID`, `AGFLOW_INSTANCE_ID`, `AGFLOW_CORRELATION_ID`, etc.).
7. **Hash de contenu** : un hash global est calculé et stocké pour détecter les régénérations inutiles.

### Aperçu sans écriture

Endpoint : `GET /api/admin/agents/{agent_id}/config-preview?profile_id=…` retourne un objet `ConfigPreview` sans rien écrire sur disque :

```json
{
  "prompt_md": "string — prompt final rendu",
  "mcp_json": { … },
  "tools_json": [ … ],
  "env_file": "string — contenu du .env",
  "skills": [
    { "skill_id": "uuid", "name": "string", "content_md": "string" }
  ],
  "validation_errors": [
    "Variable XXX non résoluble (machine 'foo' inconnue)"
  ],
  "image_status": "missing | stale | fresh",
  "profile_name": "string ou null",
  "broken_document_ids": [ "uuid", … ]
}
```

`validation_errors` agrège toutes les erreurs détectées sans bloquer. `broken_document_ids` liste les documents référencés par le profil qui n'existent plus dans le rôle.

### Régénération forcée

`POST /api/admin/agents/{id}/generate` régénère tous les fichiers en écrasant l'existant. `DELETE /api/admin/agents/{id}/generated` efface complètement le workspace de l'agent.

### Listing

`GET /api/admin/agents/{id}/generated` liste les fichiers présents dans le workspace avec leur taille et leur date de modification.

### Image status

Au moment de la génération, le service vérifie aussi que **l'image Docker** de l'agent est disponible et à jour. Trois statuts :

- `fresh` : image construite avec le `content_hash` actuel du dockerfile, présente localement.
- `stale` : image construite mais avec un hash différent (le dockerfile a changé depuis le dernier build).
- `missing` : aucune image n'est construite ou présente localement.

`stale` et `missing` empêchent l'instanciation effective (renvoient 409 sur `POST /sessions/{id}/agents`) — il faut d'abord builder via M1.

## 4. Lien entre les trois mécanismes

```
Agent (catalogue)
  ├── dockerfile_id          → M1 : image Docker
  ├── role_id                → M2 : identité + documents
  ├── mcp_bindings           → M3 : tools disponibles à l'agent
  ├── skill_bindings         → M3 : compétences activées
  ├── agent_api_contracts    → cette section 1 : APIs externes
  ├── agent_profiles         → cette section 2 : missions
  └── templates              → 13 : rendu Jinja2 des fichiers ci-dessus

Au runtime :
  Generate → produit le workspace/ avec tous les fichiers
  ↓
  Container Docker démarre avec workspace/ monté en /workspace
  ↓
  Agent lit /workspace/prompt.md, /workspace/config.toml, /workspace/skills.md, /workspace/docs/
  ↓
  L'agent reçoit des work via stdin et y répond via stdout
```

Tout l'écosystème de M2 / M3 / M4 / 13 / 14 converge vers la **production déterministe du workspace d'un agent** au moment où on l'instancie.
