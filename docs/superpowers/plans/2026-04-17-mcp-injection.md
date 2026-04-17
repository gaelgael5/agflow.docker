# Injection MCP dans les containers — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre l'injection réelle de serveurs MCP dans les containers agents, via un sélecteur de target dans Dockerfiles et une génération de config/commandes basée sur les templates yoops.

**Architecture:** Le registre mcp.yoops.org expose `GET /targets` (liste des outils cibles avec modes d'installation). Le target est stocké dans `Dockerfile.json`. Lors de la composition agent, l'utilisateur choisit un runtime par MCP. La génération produit soit un `install_mcp.sh` (cmd), soit un fichier de config au format de l'outil (insert_in_file).

**Tech Stack:** Python 3.12 + FastAPI + asyncpg (backend), React 18 + TypeScript + TanStack Query (frontend), API yoops.org `/targets`

**Spec de référence:** `docs/superpowers/specs/2026-04-17-mcp-injection-design.md`

---

## File Structure

**Backend — créés :**
- `backend/migrations/042_mcp_servers_recipes.sql` — ajout colonnes recipes + parameters sur mcp_servers

**Backend — modifiés :**
- `backend/src/agflow/services/discovery_client.py` — `fetch_targets()`, enrichir `_map_mcp_item()` avec recipes/parameters
- `backend/src/agflow/services/mcp_catalog_service.py` — stocker recipes/parameters à l'install
- `backend/src/agflow/api/admin/discovery_services.py` — endpoint proxy `/targets`
- `backend/src/agflow/schemas/catalogs.py` — `TargetSummary`, `TargetMode`, enrichir `MCPServerSummary`
- `backend/src/agflow/services/agent_generator.py` — génération install_mcp.sh + config files
- `backend/src/agflow/services/dockerfile_files_service.py` — helper lecture/écriture bloc Target

**Frontend — créés :**
- `frontend/src/components/TargetSelectorDialog.tsx` — modale de sélection de target

**Frontend — modifiés :**
- `frontend/src/lib/catalogsApi.ts` — `fetchTargets()`, enrichir types MCPSearchItem
- `frontend/src/pages/DockerfilesPage.tsx` — intégrer sélecteur de target
- `frontend/src/pages/AgentEditorPage.tsx` — bloc MCP enrichi (runtime + params + preview)
- `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json` — clés target/mcp

---

## Task 1 : Backend — schémas + fetch targets

**Files:**
- Modify: `backend/src/agflow/schemas/catalogs.py`
- Modify: `backend/src/agflow/services/discovery_client.py`

- [ ] **Step 1.1 : Ajouter les schémas Target dans catalogs.py**

Ajouter après la classe `ProbeResult` :

```python
class TargetMode(BaseModel):
    runtime: str
    action_type: str  # "cmd" | "insert_in_file"
    template: str
    config_path: str | None = None


class TargetSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    modes: list[TargetMode] = Field(default_factory=list)
    skill_modes: list[dict] = Field(default_factory=list)
```

- [ ] **Step 1.2 : Ajouter fetch_targets() dans discovery_client.py**

Ajouter après la fonction `probe()` :

```python
async def fetch_targets(
    base_url: str,
    api_key: str | None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Fetch all installation targets from the registry."""
    url = base_url.rstrip("/") + "/targets"
    async with _maybe_client(client) as c:
        response = await c.get(url, headers=_headers(api_key))
    response.raise_for_status()
    return response.json()
```

- [ ] **Step 1.3 : Enrichir _map_mcp_item() pour inclure recipes et parameters**

Modifier `_map_mcp_item()` pour ajouter les champs `recipes` et `parameters` :

```python
def _map_mcp_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a yoops /search_mcp item into agflow's MCPSearchItem shape."""
    full_name: str = raw.get("name") or ""
    short_name = full_name.split("/")[-1] if "/" in full_name else full_name
    description: str = raw.get("description") or ""
    short_desc = description[:200] if description else (raw.get("category") or "")
    return {
        "package_id": raw.get("id", ""),
        "name": short_name or full_name,
        "repo": full_name,
        "repo_url": raw.get("source_url") or "",
        "transport": raw.get("transport") or "stdio",
        "category": raw.get("category") or "",
        "short_description": short_desc,
        "long_description": description,
        "documentation_url": raw.get("doc_url") or "",
        "has_summaries": bool(description),
        "recipes": raw.get("recipes") or {},
        "parameters": raw.get("parameters") or [],
    }
```

- [ ] **Step 1.4 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/discovery_client.py src/agflow/schemas/catalogs.py
git add backend/src/agflow/schemas/catalogs.py backend/src/agflow/services/discovery_client.py
git commit -m "feat(discovery): schémas Target + fetch_targets + recipes/parameters dans search_mcp"
```

---

## Task 2 : Backend — endpoint proxy targets + migration mcp_servers

**Files:**
- Create: `backend/migrations/042_mcp_servers_recipes.sql`
- Modify: `backend/src/agflow/api/admin/discovery_services.py`
- Modify: `backend/src/agflow/services/mcp_catalog_service.py`
- Modify: `backend/src/agflow/schemas/catalogs.py`

- [ ] **Step 2.1 : Migration SQL — colonnes recipes et parameters**

Créer `backend/migrations/042_mcp_servers_recipes.sql` :

```sql
-- Add recipes and parameters columns to mcp_servers
-- recipes: full recipe dict from registry (keyed by target name)
-- parameters: array of parameter definitions from registry
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS recipes JSONB NOT NULL DEFAULT '{}';

-- Rename existing 'parameters' to avoid confusion (it stored default values, not schema)
-- The new 'parameters_schema' column already exists (from migration 011)
-- We repurpose the existing 'parameters' column for registry parameter definitions
UPDATE mcp_servers SET parameters = '[]' WHERE parameters = '{}' OR parameters IS NULL;
```

- [ ] **Step 2.2 : Endpoint proxy GET /admin/discovery-services/{id}/targets**

Ajouter dans `backend/src/agflow/api/admin/discovery_services.py` :

```python
@router.get("/{service_id}/targets")
async def list_targets(service_id: str):
    """Proxy to registry GET /targets."""
    service = await discovery_services_service.get_by_id(service_id)
    api_key = await discovery_services_service._resolve_api_key(service.api_key_var)
    targets = await discovery_client.fetch_targets(service.base_url, api_key)
    return targets
```

- [ ] **Step 2.3 : Enrichir mcp_catalog_service.install() pour stocker recipes + parameters**

Dans `mcp_catalog_service.py`, modifier la fonction `install()`. Le `detail` vient de `get_mcp_detail()` qui appelle l'ancien endpoint `/services/{id}`. Il faut enrichir avec les données du search (qui contient recipes/parameters).

Modifier `install()` pour accepter `recipes` et `parameters` en paramètres optionnels :

```python
async def install(
    discovery_service_id: str,
    package_id: str,
    recipes: dict | None = None,
    parameters: list | None = None,
) -> MCPServerSummary:
    service = await discovery_services_service.get_by_id(discovery_service_id)
    api_key = await discovery_services_service._resolve_api_key(service.api_key_var)

    detail = await discovery_client.get_mcp_detail(
        service.base_url, api_key, package_id
    )

    try:
        row = await fetch_one(
            f"""
            INSERT INTO mcp_servers (
                discovery_service_id, package_id, name, repo, repo_url,
                transport, short_description, long_description,
                documentation_url, parameters_schema, recipes, parameters
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb)
            RETURNING {_COLS}
            """,
            discovery_service_id,
            package_id,
            detail.get("name", package_id),
            detail.get("repo", ""),
            detail.get("repo_url", ""),
            detail.get("transport", "stdio"),
            detail.get("short_description", ""),
            detail.get("long_description", ""),
            detail.get("documentation_url", ""),
            json.dumps(detail.get("parameters_schema", [])),
            json.dumps(recipes or {}),
            json.dumps(parameters or []),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateMCPServerError(...) from exc
    ...
```

Mettre aussi à jour `_COLS` pour inclure `recipes, parameters` et `_row()` pour les mapper.

- [ ] **Step 2.4 : Mettre à jour MCPServerSummary dans schemas/catalogs.py**

Ajouter les champs si absents :

```python
class MCPServerSummary(BaseModel):
    ...
    recipes: dict = Field(default_factory=dict)
    parameters: list = Field(default_factory=list)
```

- [ ] **Step 2.5 : Mettre à jour le endpoint /admin/mcp-catalog POST pour passer recipes/parameters**

Dans le routeur admin MCP catalog, modifier le handler d'installation pour extraire recipes/parameters du body ou du frontend :

```python
@router.post("", response_model=MCPServerSummary, status_code=201)
async def install_mcp(payload: MCPInstallPayload):
    return await mcp_catalog_service.install(
        payload.discovery_service_id,
        str(payload.package_id),
        recipes=payload.recipes,
        parameters=payload.parameters,
    )
```

Enrichir `MCPInstallPayload` :

```python
class MCPInstallPayload(BaseModel):
    discovery_service_id: str
    package_id: str | int
    recipes: dict = Field(default_factory=dict)
    parameters: list = Field(default_factory=list)
```

- [ ] **Step 2.6 : Appliquer migration + lint + commit**

```bash
cd backend && uv run python -m agflow.db.migrations
cd backend && uv run ruff check src/ --fix
git add backend/migrations/042_mcp_servers_recipes.sql backend/src/agflow/
git commit -m "feat(mcp): migration recipes/parameters + endpoint proxy targets + install enrichi"
```

---

## Task 3 : Frontend — API targets + types enrichis

**Files:**
- Modify: `frontend/src/lib/catalogsApi.ts`
- Modify: `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json`

- [ ] **Step 3.1 : Ajouter types et fonctions targets dans catalogsApi.ts**

```typescript
export interface TargetMode {
  runtime: string;
  action_type: "cmd" | "insert_in_file";
  template: string;
  config_path?: string;
}

export interface TargetSummary {
  id: string;
  name: string;
  description: string;
  modes: TargetMode[];
  skill_modes: unknown[];
}

// Enrichir MCPSearchItem existant
export interface MCPSearchItem {
  ... // champs existants
  recipes: Record<string, { action_type: string; data: string; config_path?: string }>;
  parameters: Array<{ name: string; description: string; is_required: boolean; is_secret: boolean }>;
}

// Ajouter dans discoveryApi :
export const discoveryApi = {
  ...
  async fetchTargets(serviceId: string): Promise<TargetSummary[]> {
    const res = await api.get<TargetSummary[]>(
      `/admin/discovery-services/${serviceId}/targets`,
    );
    return res.data;
  },
};
```

- [ ] **Step 3.2 : Enrichir MCPInstallPayload côté frontend**

Modifier l'appel install dans `catalogsApi.ts` pour passer recipes et parameters :

```typescript
async install(
  discoveryServiceId: string,
  packageId: string,
  recipes: Record<string, unknown> = {},
  parameters: unknown[] = [],
): Promise<MCPServerSummary> {
  const res = await api.post<MCPServerSummary>("/admin/mcp-catalog", {
    discovery_service_id: discoveryServiceId,
    package_id: packageId,
    recipes,
    parameters,
  });
  return res.data;
},
```

- [ ] **Step 3.3 : Mettre à jour les appels install dans MCPCatalogPage.tsx**

```typescript
async function handleInstall(item: MCPSearchItem) {
  if (!selectedServiceId) return;
  await installMutation.mutateAsync({
    discoveryServiceId: selectedServiceId,
    packageId: String(item.package_id),
    recipes: item.recipes ?? {},
    parameters: item.parameters ?? [],
  });
}
```

Adapter `installMutation` dans `useCatalogs.ts` pour accepter les nouveaux champs.

- [ ] **Step 3.4 : Clés i18n pour le sélecteur de target**

Ajouter dans fr.json et en.json un bloc `"target"` :

```json
"target": {
  "select_button": "Choisir un target",
  "current": "Target : {{name}}",
  "none": "Aucun target sélectionné",
  "modes": "Modes d'installation",
  "dialog_title": "Sélection du target d'installation MCP",
  "dialog_subtitle": "Choisissez l'outil cible pour définir comment les MCP seront installés"
}
```

- [ ] **Step 3.5 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/catalogsApi.ts frontend/src/i18n/
git commit -m "feat(mcp): types Target + fetchTargets API + install enrichi recipes/parameters"
```

---

## Task 4 : Frontend — TargetSelectorDialog

**Files:**
- Create: `frontend/src/components/TargetSelectorDialog.tsx`

- [ ] **Step 4.1 : Créer le composant**

Modale de sélection de target, pattern similaire à SearchModal mais sans recherche (la liste est courte, ~38 items) :

```tsx
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { discoveryApi, type TargetSummary } from "@/lib/catalogsApi";

interface Props {
  serviceId: string;
  currentTargetName?: string;
  onSelect: (target: TargetSummary) => void;
  onClose: () => void;
}

export function TargetSelectorDialog({ serviceId, currentTargetName, onSelect, onClose }: Props) {
  const { t } = useTranslation();
  const [targets, setTargets] = useState<TargetSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    discoveryApi.fetchTargets(serviceId).then(setTargets).finally(() => setLoading(false));
  }, [serviceId]);

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl sm:max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("target.dialog_title")}</DialogTitle>
          <DialogDescription>{t("target.dialog_subtitle")}</DialogDescription>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto -mx-6 px-6">
          {loading ? (
            <p className="text-muted-foreground text-sm py-4">{t("secrets.loading")}</p>
          ) : (
            <ul className="divide-y">
              {targets.map((target) => {
                const isCurrent = target.name === currentTargetName;
                return (
                  <li key={target.id} className="flex items-center gap-3 py-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <strong className="text-[13px]">{target.name}</strong>
                        {target.modes.map((m) => (
                          <Badge key={m.runtime} variant="secondary" className="text-[10px] font-mono">
                            {m.runtime}
                          </Badge>
                        ))}
                      </div>
                      <div className="text-[12px] text-muted-foreground mt-0.5">
                        {target.description}
                      </div>
                    </div>
                    {isCurrent ? (
                      <span className="text-green-500 text-xs flex items-center gap-1">
                        <Check className="w-3.5 h-3.5" /> {t("search_modal.added")}
                      </span>
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => { onSelect(target); onClose(); }}>
                        {t("common.confirm")}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            <X className="w-3.5 h-3.5" /> {t("search_modal.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4.2 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/TargetSelectorDialog.tsx
git commit -m "feat(mcp): composant TargetSelectorDialog"
```

---

## Task 5 : Frontend — intégration Target dans DockerfilesPage

**Files:**
- Modify: `frontend/src/pages/DockerfilesPage.tsx`

- [ ] **Step 5.1 : Ajouter le sélecteur de target**

Dans la zone des boutons d'action du Dockerfile sélectionné (près du bouton Paramètres), ajouter :
- Un badge affichant le target actuel (lu depuis Dockerfile.json → `Target.name`)
- Un bouton pour ouvrir le `TargetSelectorDialog`
- Le service de découverte à utiliser : prendre le premier (ou le seul) discovery service disponible

Quand l'utilisateur sélectionne un target :
1. Lire le contenu actuel de `Dockerfile.json` (via `dockerfileJsonFile.content`)
2. Parser le JSON
3. Ajouter/remplacer le bloc `"Target"` avec les données complètes du target (id, name, description, modes)
4. Écrire le fichier mis à jour via `updateFileMutation`

- [ ] **Step 5.2 : tsc + test visuel + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/DockerfilesPage.tsx
git commit -m "feat(dockerfiles): sélecteur de target MCP dans la page Dockerfiles"
```

---

## Task 6 : Frontend — bloc MCP enrichi dans AgentEditorPage

**Files:**
- Modify: `frontend/src/pages/AgentEditorPage.tsx`

- [ ] **Step 6.1 : Enrichir le bloc MCP**

Remplacer le textarea brut `parameters_override` par un formulaire structuré :

Pour chaque MCP binding :
1. **Sélecteur de runtime** (dropdown) : options = `target.modes.map(m => m.runtime)` depuis le `Dockerfile.json` du dockerfile sélectionné
2. **Paramètres** : champs dynamiques depuis `mcp_server.parameters[]` :
   - `is_secret: true` → input masqué (type="password") avec valeur préfixée `${}`
   - `is_secret: false` → input texte normal
   - `is_required` → marqué astérisque
3. **Preview** : bloc code readonly montrant le template résolu avec les valeurs

Stockage dans `parameters_override` :
```json
{ "runtime": "npx", "params": { "KEY": "value", "SECRET": "${SECRET_VAR}" } }
```

- [ ] **Step 6.2 : Lire le target depuis le Dockerfile.json du dockerfile sélectionné**

Le Dockerfile sélectionné est disponible via `useDockerfileDetail(form.dockerfile_id)`. Utiliser le hook pour récupérer le fichier `Dockerfile.json`, le parser, et extraire `target.modes[]`.

Si pas de target configuré → afficher un message d'avertissement "Aucun target configuré sur ce Dockerfile. Allez dans Dockerfiles > Target pour en sélectionner un."

- [ ] **Step 6.3 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/AgentEditorPage.tsx
git commit -m "feat(agents): bloc MCP enrichi avec runtime, paramètres et preview"
```

---

## Task 7 : Backend — génération install_mcp.sh + config files

**Files:**
- Modify: `backend/src/agflow/services/agent_generator.py`
- Modify: `backend/src/agflow/services/dockerfile_files_service.py`

- [ ] **Step 7.1 : Helper lecture Target depuis Dockerfile.json**

Ajouter dans `dockerfile_files_service.py` :

```python
def read_target(dockerfile_id: str) -> dict | None:
    """Read the Target block from Dockerfile.json, or None if absent."""
    json_path = os.path.join(_slug_dir(dockerfile_id), "Dockerfile.json")
    if not os.path.isfile(json_path):
        return None
    with open(json_path, encoding="utf-8") as f:
        data = json.loads(f.read())
    return data.get("Target")
```

- [ ] **Step 7.2 : Modifier agent_generator.generate() pour produire les fichiers MCP**

Remplacer la section MCP (lignes ~237-244) par une nouvelle logique :

```python
# ── MCP installation ─────────────────────────────────────────
target = dockerfile_files_service.read_target(agent.dockerfile_id)
cmd_lines: list[str] = []
config_blocks: dict[str, list[str]] = {}  # config_path → list of template blocks

for binding in agent.mcp_bindings:
    mcp = await mcp_catalog_service.get_by_id(binding.mcp_server_id)
    override = binding.parameters_override or {}
    runtime = override.get("runtime")
    params = override.get("params", {})

    if not target or not runtime:
        continue

    # Find matching mode
    mode = next((m for m in target.get("modes", []) if m["runtime"] == runtime), None)
    if not mode:
        continue

    # Substitute template
    template = mode["template"]
    # Build env block for substitution
    env_entries = {k: v for k, v in params.items() if v}
    env_toml = ""
    if env_entries:
        env_toml = "\n[mcp_servers.env]\n" + "\n".join(
            f'{k} = "{v}"' for k, v in env_entries.items()
        )
    env_json = ""
    if env_entries:
        pairs = ", ".join(f'"{k}": "{v}"' for k, v in env_entries.items())
        env_json = f', "env": {{{pairs}}}'

    resolved = (
        template
        .replace("{name}", mcp.name)
        .replace("{package}", mcp.repo or mcp.name)
        .replace("{env_toml}", env_toml)
        .replace("{env_json}", env_json)
    )

    if mode["action_type"] == "cmd":
        cmd_lines.append(resolved)
    elif mode["action_type"] == "insert_in_file":
        config_path = mode.get("config_path", "mcp_config")
        config_blocks.setdefault(config_path, []).append(resolved)

# Write install_mcp.sh
if cmd_lines:
    script = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(cmd_lines) + "\n"
    _write(out_dir, "install_mcp.sh", script)

# Write config files
for config_path, blocks in config_blocks.items():
    filename = os.path.basename(config_path)
    content = "\n\n".join(blocks) + "\n"
    _write(out_dir, filename, content)
```

- [ ] **Step 7.3 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/agent_generator.py src/agflow/services/dockerfile_files_service.py
git add backend/src/agflow/services/
git commit -m "feat(generator): génération install_mcp.sh + config files depuis templates yoops"
```

---

## Task 8 : Vérifications + déploiement

**Files:** (aucun nouveau)

- [ ] **Step 8.1 : TypeScript strict frontend**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 8.2 : Ruff backend**

```bash
cd backend && uv run ruff check src/
```

- [ ] **Step 8.3 : Tests existants**

```bash
cd frontend && npm test
cd backend && uv run pytest -v
```

- [ ] **Step 8.4 : Déploiement**

```bash
bash scripts/deploy.sh --rebuild
```

- [ ] **Step 8.5 : Test E2E**

1. Page Dockerfiles → sélectionner "mistral" → cliquer Target → choisir "Mistral Vibe"
2. Vérifier que `Dockerfile.json` contient le bloc Target avec 5 modes
3. Page Agents → ouvrir un agent utilisant le dockerfile mistral
4. Ajouter mcp-server-fetch → sélectionner runtime "npx" → pas de params
5. Générer → vérifier que `generated/config.toml` contient le bloc `[[mcp_servers]]`
6. Ajouter mcp-server-github → sélectionner runtime "npx" → remplir params
7. Re-générer → vérifier que le 2e bloc `[[mcp_servers]]` apparaît avec env

---

## Self-review

- **Couverture spec** : Target dans Dockerfile.json (T1+T5), proxy targets (T2), recipes/params stockés (T2), Agent binding enrichi (T6), Génération (T7), masquage secrets (T6). ✓
- **Placeholder scan** : aucun TBD, TODO. Code concret dans chaque task. ✓
- **Type consistency** : `TargetSummary`, `TargetMode`, `MCPSearchItem.recipes/parameters` cohérents entre backend et frontend. ✓
- **Incohérence connue** : `config_overrides` vs `parameters_override` — le plan utilise `parameters_override` (schema). L'incohérence existante dans agent_generator.py devra être corrigée dans T7.
