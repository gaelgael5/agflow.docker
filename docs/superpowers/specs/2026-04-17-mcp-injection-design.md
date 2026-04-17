# Injection MCP dans les containers agents — design

**Date** : 2026-04-17
**Modules** : M1 (Dockerfiles), M4 (Agents), Génération
**Scope** : Backend + Frontend

## Contexte

Les agents agflow tournent dans des containers Docker. Chaque type d'agent CLI (claude-code, mistral-vibe, codex, gemini…) a sa propre façon de configurer les serveurs MCP :
- **Commande** (`cmd`) : `claude mcp add {name} -- npx -y {package}`
- **Fichier de config** (`insert_in_file`) : écrire dans `~/.vibe/config.toml`, `mcp_config.json`, etc.

Aujourd'hui, le catalogue MCP existe (M3) et les bindings agent↔MCP sont stockés en DB, mais **aucun mécanisme n'injecte réellement la config MCP dans le container**. Le `mcp.json` généré n'est pas utilisé.

Le registre mcp.yoops.org expose une API `/targets` qui fournit pour chaque outil cible (Mistral Vibe, claude_code, Cursor…) la liste des modes d'installation avec templates et chemins de fichier.

## Décisions validées

| Dimension | Choix |
|---|---|
| Source des targets | API `GET /targets` de mcp.yoops.org |
| Stockage target | Bloc `"Target"` dans `Dockerfile.json` (fichier sur disque) |
| Choix du runtime (npx/uvx/docker…) | Au niveau du binding agent↔MCP (pas du Dockerfile) |
| Modes couverts (V1) | `cmd` + `insert_in_file` (pas `docker_run` pour l'instant) |
| Paramètres secrets | Stockés comme `${VAR}` (référence), résolus à la génération, **masqués à l'affichage** |
| Génération | Template substitution → `install_mcp.sh` (cmd) ou fichier config (insert_in_file) |

## API yoops `/targets`

```json
{
  "id": "576ef3a9-...",
  "name": "Mistral Vibe",
  "description": "Mistral Vibe CLI coding assistant (~/.vibe/config.toml)",
  "modes": [
    {
      "runtime": "npx",
      "action_type": "insert_in_file",
      "template": "[[mcp_servers]]\nname = \"{name}\"\ntransport = \"stdio\"\ncommand = \"npx\"\nargs = [\"-y\", \"{package}\"]{env_toml}",
      "config_path": "~/.vibe/config.toml"
    },
    { "runtime": "uvx", "action_type": "insert_in_file", "template": "...", "config_path": "~/.vibe/config.toml" },
    { "runtime": "docker", "action_type": "insert_in_file", "template": "...", "config_path": "~/.vibe/config.toml" },
    { "runtime": "http", "action_type": "insert_in_file", "template": "...", "config_path": "~/.vibe/config.toml" },
    { "runtime": "streamable-http", "action_type": "insert_in_file", "template": "...", "config_path": "~/.vibe/config.toml" }
  ],
  "skill_modes": []
}
```

Placeholders dans les templates : `{name}`, `{package}`, `{env_toml}`, `{env_json}`.

## Pièce 1 : Dockerfile — bloc Target

### Dockerfile.json sur disque

Ajout d'un bloc `"Target"` frère de `"docker"` et `"Params"` :

```json
{
  "docker": { ... },
  "Params": { ... },
  "Target": {
    "id": "576ef3a9-...",
    "name": "Mistral Vibe",
    "description": "Mistral Vibe CLI coding assistant",
    "modes": [
      {
        "runtime": "npx",
        "action_type": "insert_in_file",
        "template": "[[mcp_servers]]\nname = \"{name}\"...",
        "config_path": "~/.vibe/config.toml"
      },
      { "runtime": "uvx", ... },
      { "runtime": "docker", ... },
      { "runtime": "http", ... },
      { "runtime": "streamable-http", ... }
    ]
  }
}
```

Le target complet (tous les modes) est stocké — le choix du runtime se fait dans l'agent.

### Page Dockerfiles — sélecteur de target

- Modale de recherche (même pattern que MCP/Skills) alimentée par `GET /targets` via le discovery service
- L'utilisateur sélectionne un target (ex: "Mistral Vibe")
- Le bloc Target est écrit dans Dockerfile.json
- Affichage dans l'UI : nom du target + liste des runtimes disponibles (lecture seule, informatif)

### Backend

- Nouveau endpoint proxy : `GET /api/admin/discovery-services/{id}/targets` → forward vers `GET {base_url}/targets`
- Nouveau helper dans `discovery_client.py` : `fetch_targets(base_url, api_key) -> list[Target]`
- Mise à jour de `dockerfile_files_service.py` : lecture/écriture du bloc Target dans Dockerfile.json

## Pièce 2 : Agent — binding MCP avec runtime et paramètres

### Page Agent Editor — bloc MCP enrichi

Pour chaque MCP ajouté à l'agent :

1. **Sélecteur de runtime** : dropdown des modes disponibles depuis `dockerfile.Target.modes[]`
2. **Formulaire de paramètres** : champs dynamiques depuis `mcp_servers.parameters` (name, description, is_required, is_secret)
   - Champs `is_secret` : masqués à l'affichage (même convention que .env), stockés comme `${VAR_NAME}`
3. **Preview** : template résolu (avec valeurs substituées) en lecture seule

### Stockage

`agent_mcp_servers.parameters_override` (JSONB, existant) :

```json
{
  "runtime": "npx",
  "params": {
    "GITHUB_OWNER": "gaelgael5",
    "GITHUB_REPO": "agflow.docker",
    "GITHUB_TOKEN": "${GITHUB_TOKEN}",
    "GITHUB_BRANCH": "main"
  }
}
```

### Catalogue MCP local

Au moment de l'installation d'un MCP (`mcp_catalog_service.install()`), stocker aussi `recipes` et `parameters` depuis yoops. Migration :

```sql
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS recipes JSONB DEFAULT '{}';
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '[]';
```

## Pièce 3 : Génération

### agent_generator.py — nouvelle logique

Pour chaque MCP binding de l'agent :

1. Lire le target depuis `Dockerfile.json → Target`
2. Lire le runtime depuis `binding.parameters_override.runtime`
3. Trouver le mode correspondant dans `target.modes[runtime]`
4. Substituer les placeholders dans `mode.template` :
   - `{name}` → nom du MCP server
   - `{package}` → repo ou package identifier
   - `{env_toml}` / `{env_json}` → paramètres formatés selon le mode
5. Selon `action_type` :
   - `"cmd"` → append la commande dans `generated/install_mcp.sh`
   - `"insert_in_file"` → append le bloc dans `generated/{config_path}` (ex: `config.toml`)

### Fichiers générés

```
generated/
  install_mcp.sh        ← commandes (action_type=cmd), chmod +x
  config.toml           ← ou mcp_config.json, selon config_path
  prompt.md             ← existant
  .env                  ← existant
  run.sh                ← existant, modifié pour exécuter install_mcp.sh
```

### Entrypoint

Le `run.sh` ou l'entrypoint doit, avant de lancer l'agent :
```bash
# Install MCP servers (commandes)
[ -f /app/generated/install_mcp.sh ] && bash /app/generated/install_mcp.sh

# Config MCP (fichier déjà en place via mount ou copie)
# Le fichier config est monté au bon path via docker.Mounts dans Dockerfile.json
```

## Hors scope (V1)

- Mode `docker_run` (3e mode d'installation — V2)
- `skill_modes` (installation de skills — même pattern, à traiter après MCP)
- MCP dynamiques ajoutés en cours d'exécution (runtime hot-reload)
- Résolution de `config_path` avec expansion `~` (on mount le fichier au path exact dans le container via docker.Mounts)

## Vérification

1. Dockerfile "mistral" : sélectionner target "Mistral Vibe" → bloc Target écrit dans Dockerfile.json
2. Agent utilisant ce Dockerfile : ajouter mcp-server-fetch → choisir runtime npx → preview TOML affiché
3. Générer : fichier `config.toml` contient le bloc `[[mcp_servers]]` correct
4. Lancer le container : vérifier que `~/.vibe/config.toml` est présent et parseable par mistral-vibe
