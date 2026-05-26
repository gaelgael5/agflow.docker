# 13 — Catalogues internes et briques de composition

Ce fichier complète le module 04 en détaillant les **briques élémentaires** que l'administrateur compose pour construire les agents et les projets : templates Jinja2, scripts, providers IA, registries d'images, avatars, types de service, applications externes.

## 1. Templates Jinja2

### Modèle

Un **template** est un répertoire versionné de fichiers Jinja2 destinés à être rendus au moment du déploiement ou de la génération de fichiers de runtime. Identifié par un **slug** unique alphanumérique.

Chaque template porte un `display_name` et une `description` libres. Pas de contenu propre — le contenu vit dans les fichiers attachés.

### Nomenclature des fichiers

Chaque fichier d'un template est identifié par :
- **`filename`** : nom complet du fichier dans le repository du template.
- **`culture`** : code de langue (`fr`, `en`, …).
- **`kind`** : type de fichier (`prompt`, `mcp`, `skills`, `compose`, `swarm`, `k3s`, …).

La nomenclature canonique (sur disque dans `/app/data/templates/`) est `<slug>/<culture>.<kind>.j2` :

```
/app/data/templates/
├── claude-code-agent/
│   ├── fr.prompt.j2
│   ├── en.prompt.j2
│   ├── fr.mcp.j2
│   └── fr.skills.j2
├── outline-compose/
│   ├── fr.compose.j2
│   └── fr.swarm.j2
└── ...
```

### Cultures disponibles

Endpoint : `GET /api/admin/templates/cultures` retourne la liste des cultures supportées :

```json
[
  { "key": "fr", "label": "Français", "sort_order": 1 },
  { "key": "en", "label": "English",  "sort_order": 2 }
]
```

Les cultures sont versionnées en base et peuvent être étendues. Chaque agent / produit / projet référence une culture cible (par défaut `fr`).

### Types de fichier disponibles

Endpoint : `GET /api/admin/templates/file-types` retourne :

```json
[
  { "key": "prompt",  "label": "Prompt système",   "sort_order": 1 },
  { "key": "mcp",     "label": "Configuration MCP", "sort_order": 2 },
  { "key": "skills",  "label": "Catalogue skills",  "sort_order": 3 },
  { "key": "compose", "label": "docker-compose",    "sort_order": 4 },
  { "key": "swarm",   "label": "Docker Swarm stack","sort_order": 5 },
  …
]
```

### CRUD

Endpoints :
- `GET /api/admin/templates` — lister tous les templates avec leurs cultures disponibles.
- `POST /api/admin/templates` — créer un template (slug + display_name + description).
- `GET /api/admin/templates/{slug}` — détail avec la liste des fichiers (par culture + size).
- `PUT /api/admin/templates/{slug}` — mettre à jour les métadonnées.
- `DELETE /api/admin/templates/{slug}` — supprimer (échoue si encore référencé).
- `POST /api/admin/templates/{slug}/files` — créer un fichier (avec `filename` + `content`).
- `GET / PUT / DELETE /api/admin/templates/{slug}/files/{filename}` — opérations sur un fichier.

### Moteur de rendu

Jinja2 en mode **sandbox** :
- `SandboxedEnvironment` (pas `Environment`) → empêche l'accès aux attributs Python sensibles (`__class__`, `__mro__`, etc.).
- Pas d'`include` d'arbitraires chemins (le loader est limité au répertoire du template courant + un répertoire global de macros partagées).
- Filtres custom limités à un set whitelisté (`to_yaml`, `to_json`, `b64encode`, `slugify`, etc.).
- Pas d'exécution Python via `{% set %}`/`{{ … }}` qui appellerait du code arbitraire.

### Variables exposées au rendu

Selon le contexte de rendu :

| Contexte | Variables disponibles |
|---|---|
| Rendu d'agent (prompt, MCP, skills) | `agent`, `role`, `profile`, `mcp_bindings`, `skill_bindings`, `env`, `secrets` |
| Rendu de groupe (compose, swarm) | `group`, `project`, `runtime`, `instances`, `env`, `secrets` |
| Rendu de script | `script`, `input_values`, `env`, `machine`, `accumulated_env` |

### Référence directe par culture

Un agent (`agents`) référence ses templates de génération via les paires `<kind>_template_slug` + `<kind>_template_culture` (par exemple `prompt_template_slug` + `prompt_template_culture`). Si la culture spécifique n'a pas de fichier, le moteur tombe back sur la culture `fr` puis échoue si rien n'est trouvé.

## 2. Scripts shell

### Modèle

Un **script** (`scripts`) est un fragment shell versionné en base, paramétré, destiné à être exécuté à distance via SSH sur une machine cible. Utilisés principalement par les **scripts de groupe** (cf. module 06) en timing `before` ou `after` d'un déploiement.

### Structure

| Champ | Type | Rôle |
|---|---|---|
| `id` | UUID | Identifiant |
| `name` | string | Nom unique |
| `description` | string | Description libre |
| `content` | text | Code shell (bash, avec en-tête `#!/usr/bin/env bash`) |
| `execute_on_types_named` | UUID? | Si renseigné, le script ne peut être exécuté que sur une machine de ce named type |
| `execute_on_types_named_name` | string | Nom du named type (calculé pour affichage) |
| `input_variables` | JSONB array | Variables d'entrée (cf. ci-dessous) |
| `output_variables` | JSONB array | Variables de sortie (cf. ci-dessous) |
| `commands` | JSONB array | Sous-commandes nommées (alternative à `content` pour les scripts multi-actions) |

### Variables d'entrée (`input_variables`)

Chaque entrée :

```json
{
  "name": "KC_ADMIN_PASSWORD",
  "description": "Mot de passe admin Keycloak",
  "default": "",
  "via_env": true
}
```

- `name` : nom canonique de la variable (utilisé dans `content` via `{KC_ADMIN_PASSWORD}` ou en env si `via_env`).
- `description` : texte d'aide affiché dans l'UI.
- `default` : valeur par défaut (peut être une référence `${vault://…}` ou `${env://…}`).
- `via_env` : si `true`, la variable est exportée en variable d'environnement avant l'exécution du script (`export KC_ADMIN_PASSWORD="…" && bash script.sh`). Sinon elle est substituée littéralement dans le contenu via le pattern `{NAME}`.

### Variables de sortie (`output_variables`)

Chaque entrée :

```json
{
  "name": "client_id",
  "description": "OIDC client ID créé",
  "path": "result.client_id",
  "via_env": false
}
```

- `path` : dot-notation pour extraire la valeur de la **dernière ligne JSON du stdout**. Par exemple si le script termine par :
  ```
  echo '{"result": {"client_id": "agflow-cli", "secret": "…"}}'
  ```
  alors `path="result.client_id"` extrait `"agflow-cli"`.
- `via_env` : si `true`, la valeur est lue depuis l'environnement du process à la sortie (variable exportée par le script) plutôt que parsée du stdout.

Convention forte : **la dernière ligne du stdout d'un script qui produit des sorties est un JSON valide**. Cela évite le parsing fragile de format mixte texte+JSON.

### Sous-commandes nommées

Pour les scripts complexes, on peut déclarer des `commands` au lieu (ou en plus) de `content` :

```json
[
  { "name": "install",    "content": "apt-get install -y …" },
  { "name": "configure",  "content": "systemctl enable …" },
  { "name": "smoketest",  "content": "curl …" }
]
```

Permet à l'UI d'afficher les sections et au workflow de n'exécuter qu'une sous-commande sélectionnée.

### Endpoints

- `GET / POST /api/admin/scripts` — liste / création.
- `GET / PUT / DELETE /api/admin/scripts/{id}` — détail / mise à jour / suppression.

### Règles de déclenchement (côté `group_scripts`)

Quand un script est attaché à un groupe (`group_scripts`), il peut porter des `trigger_rules` qui conditionnent son exécution :

```json
[
  { "variable": "ENABLE_OIDC", "op": "equals",     "value": "true" },
  { "variable": "PROVIDER",    "op": "not_equals", "value": "local" },
  { "variable": "BACKUP_KEY",  "op": "is_null",    "value": "" }
]
```

Opérateurs supportés : `equals`, `not_equals`, `is_null`. Les règles sont en **AND** (toutes doivent passer pour exécuter le script).

## 3. AI Providers

### Modèle

Un **AI provider** (`ai_providers`) est une configuration de connexion à un service IA externe (Anthropic, OpenAI, Mistral, Google, etc.) pour un **type de service** donné.

### Types de service

Enum strict :
- `image_generation` : modèles de génération d'images (DALL-E, Stable Diffusion).
- `embedding` : modèles d'embeddings (text-embedding-ada-002, BGE, …).
- `llm` : modèles de langage utilisés par les agents et par les fonctions IA internes (Claude, GPT, Gemini, …).

### Configuration

Pour chaque (`service_type`, `provider_name`) :

```json
{
  "service_type": "llm",
  "provider_name": "anthropic",
  "display_name": "Anthropic Claude (production)",
  "secret_ref": "${vault://api:ANTHROPIC_API_KEY}",
  "enabled": true,
  "is_default": true
}
```

- `provider_name` : identifiant logique (anthropic / openai / mistral / google / …). Détermine le client SDK utilisé en interne.
- `display_name` : libellé pour l'UI.
- `secret_ref` : référence Harpocrate vers la clé API.
- `enabled` : actif ou non.
- `is_default` : un seul provider par `service_type` peut porter ce flag. Le default est utilisé quand le caller ne précise pas de provider explicite.

PK composite : `(service_type, provider_name)`. Plusieurs providers du même type peuvent coexister (par exemple Anthropic + OpenAI pour le `llm` ; un seul est default).

### Endpoints

- `GET /api/admin/ai-providers?service_type=llm` — lister filtré par type.
- `POST /api/admin/ai-providers` — créer.
- `PUT /api/admin/ai-providers/{service_type}/{provider_name}` — mettre à jour.
- `DELETE /api/admin/ai-providers/{service_type}/{provider_name}` — supprimer.
- `POST /api/admin/ai-providers/{service_type}/{provider_name}/test` — tester la clé via un appel léger au provider.

### Utilisation interne

| Fonction interne | Provider type utilisé |
|---|---|
| Chat-generate de Dockerfile (M1) | `llm` default |
| Génération du prompt orchestrateur d'un rôle (M2) | `llm` default |
| Génération d'images d'avatar (M3 bis / Avatars) | `image_generation` default |
| Indexation / RAG dans les MCP (si applicable) | `embedding` default |
| Agents en runtime | Configurable par agent via env_vars + secrets (l'agent appelle lui-même les providers IA depuis son container) |

## 4. Image registries

### Modèle

Une **image registry** (`image_registries`) est une déclaration de registre Docker externe d'où la plateforme peut **tirer des images** pour les conteneurs déployés (au-delà des images des agents construites localement en M1).

### Configuration

```json
{
  "id": "harbor-prod",
  "display_name": "Harbor production",
  "url": "harbor.example.com",
  "auth_type": "token",
  "credential_ref": "${vault://api:HARBOR_TOKEN}",
  "is_default": false
}
```

- `id` : slug unique.
- `url` : domaine du registre (sans `https://`).
- `auth_type` : `none` (registre public) / `basic` (user+password) / `token` (token Bearer).
- `credential_ref` : référence Harpocrate vers les credentials sérialisés au format attendu par le auth_type.
- `is_default` : si `true`, ce registre est utilisé en priorité pour les `image:` non préfixés.

### Endpoints

- `GET / POST /api/admin/image-registries`.
- `GET / PUT / DELETE /api/admin/image-registries/{id}`.

### Utilisation

Au moment du rendu d'un compose / stack / manifest, si l'image référencée est non-qualifiée (`outline:latest`) et qu'un default registry existe, le rendu la préfixe (`harbor.example.com/outline:latest`). Les credentials sont passés au démon Docker via un `docker login` préalable (côté machine cible, déclenché par les scripts de bootstrap des named types).

## 5. Service types

### Modèle

Un **service type** (`service_types`) est une catégorie qui qualifie les **rôles** (M2) et les **agents** (M4) — il indique pour quel domaine fonctionnel ce rôle ou cet agent est conçu : `documentation`, `code`, `infra`, `design`, `tests`, `analytics`, etc.

### Structure

| Champ | Type |
|---|---|
| `name` | PK slug alphanumérique |
| `display_name` | Libellé UI |
| `is_native` | `true` pour les types fournis avec la plateforme (non supprimables) |
| `position` | Ordre d'affichage |

### Endpoints

- `GET /api/admin/service-types` — lister.
- `POST /api/admin/service-types` — créer un type custom.
- `DELETE /api/admin/service-types/{name}` — supprimer. Échoue (`403`) si protégé (`is_native=true`), (`404`) si introuvable, (`409`) si encore référencé par un rôle ou un agent.

### Cas d'usage

- L'admin classifie ses rôles par `service_types` (`role.service_types = ["documentation", "tests"]`) — un rôle peut couvrir plusieurs domaines.
- Au moment de composer un agent (M4), l'UI propose seulement les rôles compatibles avec le `service_type` cible.
- Les filtres de la page Agents permettent de lister par type.

## 6. Avatars

### Modèle

Le module **Avatars** permet à l'administrateur de générer des **images de personnages** organisées par **thèmes**, principalement pour servir d'avatars de rôles / agents / utilisateurs dans l'UI.

Trois niveaux d'objets :

1. **Thèmes** (`avatar_themes`) — décrit le style global (ex: « Pirates », « Astronautes »).
2. **Personnages** (`avatar_characters`) — instance d'un thème (ex: « Capitaine Blackbeard »).
3. **Images** — variantes générées d'un personnage (typiquement 4-6 alternatives, l'admin sélectionne sa préférée).

### Thèmes

Configuration :

```json
{
  "slug": "pirates",
  "display_name": "Pirates",
  "description": "Personnages de pirates dans un style cartoon",
  "prompt": "A high-quality cartoon illustration of {character_description}, set in a pirate world with treasure ships in the background. Vivid colors, clean line art.",
  "provider": "dall-e-3",
  "size": "1024x1024",
  "quality": "hd",
  "style": "vivid"
}
```

- `prompt` : prompt **partagé** par tous les personnages du thème. Doit contenir `{character_description}` qui sera substitué par le `prompt` du personnage.
- `provider` : provider de génération (default `dall-e-3`, qui correspond au provider IA configuré en `service_type='image_generation'`).
- `size`, `quality`, `style` : paramètres passés à l'API du provider.

### Personnages

Configuration :

```json
{
  "slug": "blackbeard",
  "display_name": "Capitaine Blackbeard",
  "description": "Pirate barbu redoutable",
  "prompt": "an old man with a long black beard, wearing a tricorn hat, holding a cutlass"
}
```

Le prompt final envoyé au provider est obtenu en substituant `{character_description}` dans le prompt du thème par le `prompt` du personnage.

### Images

Endpoints :
- `POST /api/admin/avatars/{theme}/characters/{char}/generate` — lance une génération (1 image par appel). Réponse : index + filename.
- `POST /api/admin/avatars/{theme}/characters/{char}/upload` — upload manuel d'une image (multipart).
- `GET /api/admin/avatars/{theme}/characters/{char}/images` — lister.
- `GET /api/admin/avatars/{theme}/characters/{char}/images/{n}` — récupérer l'image binaire.
- `DELETE /api/admin/avatars/{theme}/characters/{char}/images/{n}` — supprimer.
- `POST /api/admin/avatars/{theme}/characters/{char}/select/{n}` — désigner l'image n comme l'image sélectionnée du personnage.

### Stockage

Les images sont stockées **sur disque** (pas en base) sous `/app/data/avatars/{theme}/{character}/{n}.png`. La base contient uniquement les métadonnées (thème, personnage, numéros d'images existantes, image sélectionnée).

### Utilisation

L'image sélectionnée d'un personnage est utilisable comme avatar :
- D'un rôle (référencé par `theme + character`).
- D'un agent (idem, hérité du rôle ou override).
- D'un utilisateur (champ `avatar_url`).

## 7. Apps cross-launcher

### Modèle

Le **cross-app launcher** est une fonctionnalité du menu top-bar qui permet de pointer vers d'autres applications de la suite (ag.flow, Harpocrate UI, Grafana, Postman, etc.) sans dupliquer leurs URLs partout.

### Configuration

Fichier `apps.json` lu par `GET /api/admin/apps` :

```json
{
  "urls": [
    {
      "key": "agflow",
      "label": "ag.flow",
      "icon": "workflow",
      "url": "https://ag.flow.example.com"
    },
    {
      "key": "harpocrate",
      "label": "Harpocrate Vault",
      "icon": "lock",
      "url": "https://vault.example.com"
    },
    {
      "key": "grafana",
      "label": "Logs (Grafana)",
      "icon": "chart-bar",
      "url": "https://log.yoops.org"
    }
  ]
}
```

### Stockage et résilience

Le fichier vit côté backend, monté en read-only. S'il est absent ou invalide (JSON cassé), la réponse retourne `{"urls": []}` et le menu ne s'affiche pas — la plateforme reste fonctionnelle.

### Pas d'édition via API

Volontairement read-only via l'API : la liste des apps liées dépend du déploiement et est gérée par l'opérateur infra, pas par l'UI.

## 8. Plateforme config (kv)

### Modèle

`platform_config` est une table de paires clé/valeur générique pour des toggles globaux et des paramètres mineurs qui ne méritent pas une table dédiée.

### Endpoints

- `GET /api/admin/platform-config` — retourne `{ key: value, … }`.
- (Pas de PUT exposé publiquement — modification via SQL direct ou migration ; les paramètres critiques passent par des endpoints spécifiques.)

### Exemples de clés typiques

- `agent_idle_timeout_seconds` : timeout des instances d'agent en idle.
- `session_default_duration_seconds` : durée par défaut des sessions.
- `max_concurrent_builds` : limite de builds Docker simultanés.
- `default_network_prefix` : préfixe du nom de réseau Docker des project_runtimes.
- `notification_admin_email` : email pour les alertes opérationnelles critiques.

### Pas de magie

Les valeurs sont des strings ; le code consommateur fait le cast typé. Cela évite les schémas JSON complexes pour des toggles simples.
