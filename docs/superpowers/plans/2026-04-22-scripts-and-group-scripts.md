# Scripts & group_scripts — Hooks de déploiement avec merge .env

## Context

Le flux de déploiement M7 (`project_deployments.push`) se contente, jusqu'ici, de pousser `docker-compose.yml` + `.env` générés sur la machine cible de chaque groupe puis d'exécuter `docker compose up -d`. Plusieurs cas réels ne rentrent pas dans ce cadre :

- **Provisioning d'un sous-réseau, DB externe, DNS** avant que les conteneurs démarrent
- **Récupération d'une IP dynamique** (DHCP) ou d'un mot de passe généré par un script, à injecter comme variable d'env
- **Tâche post-déploiement** (warmup de cache, registration auprès d'un service discovery)

Ces opérations sont souvent des scripts shell maintenus par l'utilisateur. Il faut pouvoir :
1. Les stocker et les éditer dans l'interface
2. Les référencer dans un groupe de projet avec une machine SSH cible + un timing (avant/après déploiement)
3. Les exécuter dans cet ordre au moment du `push`
4. Pour les scripts `before` qui produisent du JSON sur stdout : **merger automatiquement les clés dans le `.env`** généré, avec mapping optionnel pour renommer

## Décisions d'architecture

| Sujet | Décision |
|-------|----------|
| Stockage contenu | TEXT en BDD (table `scripts.content`) — pas de disque, cohérent avec la simplicité de gestion demandée |
| Éditeur | CodeMirror 6 + `@codemirror/legacy-modes/mode/shell` + thème `oneDark` (composant `ShellEditor.tsx`, miroir de `YamlEditor`) |
| Layout éditeur | Pleine hauteur `calc(100vh-64px)` sans dépassement : flex-col + min-h-0 sur le conteneur CodeMirror |
| Référence `execute_on_types_named` | FK facultative vers `infra_named_types(id)` ON DELETE SET NULL. Filtre l'UI des machines lors du binding. |
| Référence script → groupe | Table pivot `group_scripts(id, group_id, script_id, machine_id, timing, position, env_mapping JSONB)` |
| Ordre d'exécution | Colonne `position INT` — trie stable par `(timing, position)` dans un groupe |
| Mapping env | `env_mapping JSONB` = `{"json_key": "ENV_VAR_NAME", ...}` — override optionnel, sinon match par nom exact |
| Exécution SSH | Upload temporaire en `/tmp/agflow-script-{hex}.sh`, `chmod +x`, `bash`, puis `rm -f` (via `ssh_executor.exec_command`) |
| Merge .env | Lecture ligne-par-ligne de `generated_env`, remplacement des lignes `VAR=` dont `VAR` matche une clé collectée |
| After-scripts | Exécutés après `docker compose up -d` — leur output est loggé mais pas injecté dans `.env` (il est déjà déployé) |

## Migrations

### 070 — `scripts.sql`

```sql
CREATE TABLE scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE group_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    script_id UUID NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    machine_id UUID NOT NULL REFERENCES infra_machines(id) ON DELETE RESTRICT,
    timing VARCHAR NOT NULL CHECK (timing IN ('before', 'after')),
    position INTEGER NOT NULL DEFAULT 0,
    env_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Indexes `(group_id, timing, position)`, `(script_id)`, `(machine_id)`. Triggers `set_updated_at`.

### 071 — `scripts_execute_on_types_named.sql`

```sql
ALTER TABLE scripts
    ADD COLUMN execute_on_types_named UUID
    REFERENCES infra_named_types(id) ON DELETE SET NULL;
```

Pivot facultatif : un script peut déclarer qu'il ne tourne que sur les machines d'une variante spécifique (ex: script de provisioning Proxmox → `execute_on_types_named = Proxmox-DC1`).

## Backend

### Schémas (`schemas/scripts.py`)

- `ScriptSummary` : `id, name, description, execute_on_types_named, execute_on_types_named_name, created_at, updated_at` (sans `content`)
- `ScriptRow extends ScriptSummary` : ajoute `content`
- `ScriptCreate` / `ScriptUpdate`
- `GroupScriptRow` : `id, group_id, script_id, script_name, machine_id, machine_name, timing, position, env_mapping, timestamps`
- `GroupScriptCreate` / `GroupScriptUpdate`

### Services

- `services/scripts_service.py` — CRUD. `_FROM_JOIN` avec LEFT JOIN sur `infra_named_types` pour exposer `execute_on_types_named_name`.
- `services/group_scripts_service.py` — CRUD + `list_by_group(gid)`. `_LIST_SQL` jointure sur `scripts` et `infra_machines` pour exposer `script_name` et `machine_name`.

### API

- `api/admin/scripts.py` — `/api/admin/scripts` GET/POST, `/{id}` GET/PUT/DELETE
- `api/admin/group_scripts.py` — `/api/admin/groups/{group_id}/scripts` GET/POST, `/{link_id}` PUT/DELETE

### Intégration dans le push deploy (`api/admin/project_deployments.py`)

Nouveau flux dans `push_deployment` :

```python
# Phase 1 : before-scripts
collected_env: dict[str, str] = {}
for link in sorted(before_links, key=lambda l: l.position):
    res = await _run_group_script(link, script.content)
    if res.success:
        parsed = _parse_last_json(res.stdout)
        if parsed:
            for k, v in parsed.items():
                target = link.env_mapping.get(k, k)  # mapping ou nom exact
                collected_env[target] = str(v)

# Phase 2 : merge .env
env_text = _merge_env_with_values(deployment.generated_env, collected_env)

# ...docker compose up avec env_text...

# Phase 3 : after-scripts (pas d'injection env)
for link in sorted(after_links, key=lambda l: l.position):
    res = await _run_group_script(link, script.content)
    # juste loggé dans script_results
```

Helpers ajoutés dans le même fichier :
- `_ssh_kwargs_for_machine(machine_id)` — centralise la construction des kwargs SSH
- `_parse_last_json(stdout)` — identique à celui de `api/infra/machines.py`
- `_merge_env_with_values(env_text, values)` — lecture ligne-par-ligne, remplace `VAR=...`
- `_run_group_script(link, script_content)` — upload/exec/cleanup, retourne `{success, exit_code, stdout, stderr, script, machine, timing, position}`
- `_collect_env_from_script(link, parsed_json)` — applique `env_mapping` overrides, retourne `{target: value}`

Le retour de `push` inclut maintenant :
- `results: [...]` — inchangé, résultat par machine cible
- `scripts: [...]` — nouveau, un item par run (before + after) avec stdout/stderr/exit_code
- `collected_env_keys: [...]` — nouveau, les noms de variables effectivement injectées dans `.env` (utile pour diag)

Le status passe à `deployed` uniquement si **tous** les deploy steps **et** tous les scripts réussissent.

## Frontend

### Nouvelle page `/scripts` (menu Ressources)

`pages/ScriptsPage.tsx` :
- Layout 2 colonnes : liste à gauche (Card, scroll interne), éditeur à droite (flex-1, `calc(100vh-64px)`)
- Éditeur : Nom + dropdown `execute_on_types_named` + bouton Save + description + contenu
- Contenu : composant `ShellEditor` avec coloration bash/sh

`components/ShellEditor.tsx` — miroir de `YamlEditor.tsx` mais avec `StreamLanguage.define(shell)` depuis `@codemirror/legacy-modes`.

Dépendance ajoutée : `@codemirror/legacy-modes` (npm install).

`PageShell` accepte désormais un `className` optionnel pour permettre le layout full-height.

### Section scripts dans les groupes

Dans `pages/ProjectDetailPage.tsx` sous la liste d'instances de chaque groupe :

```tsx
<GroupScriptsSection groupId={g.id} t={t} />
```

Le composant liste les liaisons par timing (Avant / Après), chaque ligne montre :
- Badge `#position`
- Nom du script
- Machine cible
- Badge `N map` si `env_mapping` a au moins une entrée
- Boutons Edit / Remove

Le dialog `GroupScriptDialog` :
- Dropdown `script_id` — montre tous les scripts, avec `[VarianteName]` si `execute_on_types_named` déclaré
- Dropdown `machine_id` — **filtré** sur `machine.type_id === selectedScript.execute_on_types_named` quand c'est déclaré
- Dropdown `timing` — before/after
- Champ `position` (number)
- Textarea `env_mapping` — une ligne `CLE=VAR` par paire, parsée au submit

Si le script change et que la machine sélectionnée n'est plus compatible, `machineId` est reset.

### API client

`lib/scriptsApi.ts` :
- `scriptsApi` : list / get / create / update / remove
- `groupScriptsApi` : list(groupId) / create / update / remove
- Types exportés : `ScriptSummary`, `ScriptRow`, `ScriptCreatePayload`, `ScriptUpdatePayload`, `GroupScript`, `GroupScriptCreatePayload`, `GroupScriptUpdatePayload`, `ScriptTiming`

### Sidebar + route

- Lien `/scripts` dans la section Ressources (icône FileCode2)
- Route `<ScriptsPage />` dans `App.tsx`

### i18n

Nouvelle clé racine `scripts` dans `fr.json` / `en.json` : page_title, page_subtitle, list, empty, add, edit, delete_title, name, description, content, content_hint, execute_on_types_named, saved, created, deleted, group_title, group_empty, group_add, group_add_title, group_edit_title, group_script, group_machine, group_timing, group_timing_before, group_timing_after, group_position, group_env_mapping, group_env_mapping_hint, group_added, group_updated, group_removed, group_no_matching_machine.

## Vérification end-to-end

1. Créer un script sur `/scripts` :
   ```sh
   #!/bin/bash
   set -euo pipefail
   # ...
   echo '{"ip":"192.168.10.100","ctid":"114","password":"xxx"}'
   ```
2. Déclarer `execute_on_types_named = LXC-Prod` sur ce script
3. Dans un groupe de projet, lier ce script :
   - Script : sélection ci-dessus
   - Machine : (seules les machines de type LXC-Prod sont proposées)
   - Timing : before
   - Position : 0
   - env_mapping : `ip=MACHINE_IP` (une seule ligne)
4. Supposons que le `.env` généré du projet contient `MACHINE_IP=` et `POSTGRES_PASSWORD=` — lancer le déploiement
5. Vérifier dans la réponse du push :
   - `scripts: [{"script":"...", "success": true, "exit_code": 0, ...}]`
   - `collected_env_keys: ["MACHINE_IP", "ctid", "password"]`
   - `results: [{"success": true, ...}]`
6. SSH sur la machine du groupe, `cat /root/agflow.docker/projects/<slug>/.env` → `MACHINE_IP=192.168.10.100` doit être présent

## Limitations / extensions futures

- **Pas de timeout configurable** sur les runs SSH — pour l'instant le timeout d'`ssh_executor.exec_command` s'applique
- **Secrets dans les scripts** : le contenu passe en clair dans `generated_env` si les scripts stockent des secrets en stdout. À sécuriser si pertinent (chiffrage à l'écriture `.env` ou filtrage des logs)
- **Pas de réutilisation de l'auth SSH** : si le même script tourne sur 5 machines, on établit 5 connexions (une par run)
- **After-scripts** : pas encore de mécanisme pour faire dépendre l'after-script d'une valeur produite par un before-script du même groupe
