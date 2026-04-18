# Contrats OpenAPI v2 — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactoring des contrats OpenAPI : générer des scripts .sh par opération + .md index par tag, ajouter tag_overrides pour descriptions humaines, préparer managed_by_instance (M7).

**Architecture:** Le parser OpenAPI est enrichi avec `operation_to_filename()`, `generate_operation_script()`, `generate_tag_index_markdown()`. Le générateur produit un répertoire par tag contenant les .sh, plus un .md index. Les tag_overrides sont stockés en JSONB sur le contrat et éditables dans le dialog frontend.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg (backend), React 18 + TypeScript (frontend), pyyaml

**Spec de référence:** Spec v2 collée dans le chat (design v0.2 avec tag_overrides + .sh/.md)

**Code existant à modifier:** Les fichiers contrats v1 sont déjà en place (parser, service, router, dialog, generator section).

---

## File Structure

**Backend — modifiés :**
- `backend/migrations/046_contracts_tag_overrides.sql` — ajout colonnes tag_overrides + managed_by_instance
- `backend/src/agflow/schemas/contracts.py` — tag_overrides, managed_by_instance, resolved_description dans TagSummary
- `backend/src/agflow/services/openapi_parser.py` — refactoring complet : operation_to_filename, resolve_tag_description, generate_operation_script, generate_tag_index_markdown
- `backend/src/agflow/services/api_contracts_service.py` — tag_overrides dans COLS, create, update
- `backend/src/agflow/services/agent_generator.py` — section contrats : .sh + .md index
- `backend/src/agflow/api/admin/contracts.py` — passer tag_overrides au create

**Frontend — modifiés :**
- `frontend/src/lib/contractsApi.ts` — tag_overrides dans types
- `frontend/src/components/ContractFormDialog.tsx` — section tag_overrides éditable
- `frontend/src/pages/AgentEditorPage.tsx` — afficher resolved descriptions

---

## Task 1 : Migration SQL + schémas Pydantic

**Files:**
- Create: `backend/migrations/046_contracts_tag_overrides.sql`
- Modify: `backend/src/agflow/schemas/contracts.py`

- [ ] **Step 1.1 : Migration SQL**

```sql
ALTER TABLE agent_api_contracts ADD COLUMN IF NOT EXISTS tag_overrides JSONB NOT NULL DEFAULT '{}';
ALTER TABLE agent_api_contracts ADD COLUMN IF NOT EXISTS managed_by_instance UUID;
```

- [ ] **Step 1.2 : Enrichir les schémas Pydantic**

Dans `contracts.py` :

Ajouter `tag_overrides: dict[str, str] = Field(default_factory=dict)` à `ContractCreate`.

Ajouter `tag_overrides: dict[str, str] | None = None` à `ContractUpdate`.

Ajouter à `ContractSummary` :
```python
    tag_overrides: dict[str, str] = Field(default_factory=dict)
    managed_by_instance: UUID | None = None
```

Modifier `TagSummary` pour ajouter `resolved_description: str = ""`.

- [ ] **Step 1.3 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/schemas/contracts.py
git add backend/migrations/046_contracts_tag_overrides.sql backend/src/agflow/schemas/contracts.py
git commit -m "feat(contracts-v2): migration tag_overrides + managed_by_instance + schémas enrichis"
```

---

## Task 2 : Parser OpenAPI refactoring

**Files:**
- Modify: `backend/src/agflow/services/openapi_parser.py`

Refactoring complet du parser. Les fonctions existantes (`generate_tag_markdown`, `_build_curl`, `_extract_body_schema`) sont remplacées/enrichies.

- [ ] **Step 2.1 : Ajouter `operation_to_filename()`**

```python
def operation_to_filename(operation: dict[str, Any]) -> str:
    """Derive a clean PascalCase .sh filename from the operation."""
    op_id = operation.get("operation_id", "") or operation.get("operationId", "")
    summary = operation.get("summary", "")

    if op_id:
        parts = op_id.split("_")
        api_idx = next((i for i, p in enumerate(parts) if p == "api"), len(parts))
        meaningful = parts[:api_idx]
        if meaningful:
            name = "".join(p.capitalize() for p in meaningful)
        else:
            name = "".join(p.capitalize() for p in parts[:3])
    elif summary:
        name = "".join(w.capitalize() for w in summary.split() if w.isalpha())
    else:
        method = operation.get("method", "Get").capitalize()
        path_parts = [p for p in operation.get("path", "").split("/") if p and not p.startswith("{")]
        name = method + "".join(p.capitalize() for p in path_parts[-2:])

    return f"{name}.sh"
```

- [ ] **Step 2.2 : Ajouter `resolve_tag_description()`**

```python
def resolve_tag_description(tag: dict[str, Any], overrides: dict[str, str]) -> str:
    """Resolve tag description: manual override > spec description > tag name."""
    override = overrides.get(tag.get("slug", "")) or overrides.get(tag.get("name", ""))
    if override:
        return override
    if tag.get("description"):
        return tag["description"]
    return tag.get("name", "")
```

- [ ] **Step 2.3 : Ajouter `generate_operation_script()`**

Fonction complète qui génère un script bash par opération avec :
- Shebang + header commentaire (opName — summary, description wrappée)
- Usage line avec path params comme args positionnels
- Validation ${N:?Usage...} pour chaque arg
- Commande curl avec auth, body, query params requis
- Le code complet est dans la spec v2 section "Génération du script .sh"

- [ ] **Step 2.4 : Ajouter `generate_tag_index_markdown()`**

```python
def generate_tag_index_markdown(
    tag_name: str,
    tag_description: str,
    base_url: str,
    auth_header: str,
    auth_prefix: str,
    auth_secret_ref: str,
    operations: list[dict[str, Any]],
) -> str:
    """Génère le fichier markdown index d'un tag avec liens vers les .sh."""
    lines = [f"# {tag_name}", ""]
    lines.append(tag_description)
    lines.append("")
    lines.append(f"Base URL : `{base_url}`")
    if auth_secret_ref:
        lines.append(f"Auth : `{auth_header}: {auth_prefix} {auth_secret_ref}`")
    lines.append("")

    for op in operations:
        lines.append(f"## {op['name']}")
        if op["description"]:
            lines.append(op["description"])
        lines.append(f"`{op['path']}`")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2.5 : Ajouter helper `_wrap_comment()` et `_truncate()`**

```python
def _wrap_comment(text: str, width: int = 74) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines

def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"
```

- [ ] **Step 2.6 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/openapi_parser.py
git add backend/src/agflow/services/openapi_parser.py
git commit -m "feat(contracts-v2): parser enrichi — operation_to_filename, scripts .sh, .md index, tag resolution"
```

---

## Task 3 : Service CRUD — tag_overrides + managed_by_instance

**Files:**
- Modify: `backend/src/agflow/services/api_contracts_service.py`

- [ ] **Step 3.1 : Ajouter les colonnes aux SUMMARY_COLS et _row_to_summary**

Ajouter `tag_overrides, managed_by_instance` à `_SUMMARY_COLS`.

Mapper dans `_row_to_summary` :
```python
tag_overrides=json.loads(row["tag_overrides"]) if isinstance(row["tag_overrides"], str) else (row["tag_overrides"] or {}),
managed_by_instance=row.get("managed_by_instance"),
```

- [ ] **Step 3.2 : Ajouter tag_overrides au create() et update()**

Dans `create()` : ajouter paramètre `tag_overrides: dict | None = None`, insérer en $14::jsonb.

Dans `update()` : ajouter `"tag_overrides"` à la liste des champs updatables, traiter comme jsonb.

- [ ] **Step 3.3 : Passer tag_overrides dans le routeur**

Dans `contracts.py` routeur, `create_contract()` : ajouter `tag_overrides=payload.tag_overrides`.

- [ ] **Step 3.4 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/api_contracts_service.py src/agflow/api/admin/contracts.py
git add backend/src/agflow/services/api_contracts_service.py backend/src/agflow/api/admin/contracts.py
git commit -m "feat(contracts-v2): tag_overrides + managed_by_instance dans service + routeur"
```

---

## Task 4 : Générateur — scripts .sh + .md index

**Files:**
- Modify: `backend/src/agflow/services/agent_generator.py`

- [ ] **Step 4.1 : Remplacer la section contrats**

La section actuelle (lignes ~328-362) génère un seul .md par tag via `_oapi.generate_tag_markdown()`. La remplacer par :

Pour chaque contrat → pour chaque tag :
1. Créer le sous-répertoire `{tag_slug}/` pour les .sh
2. Pour chaque opération du tag : générer le .sh via `_oapi.generate_operation_script()`, écrire, `chmod +x`
3. Générer le .md index via `_oapi.generate_tag_index_markdown()` avec les refs vers les .sh
4. Utiliser `_oapi.resolve_tag_description(tag, contract.tag_overrides)` pour la description

Le `contract_context` pour le template doit inclure les descriptions résolues.

Les refs dans le prompt utilisent `{ref_prefix}/{contract.output_dir}/{contract.slug}/{tag_slug}.md` pour le .md et `{ref_prefix}/{contract.output_dir}/{contract.slug}/{tag_slug}/{OpName}.sh` pour les scripts.

- [ ] **Step 4.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/agent_generator.py
git add backend/src/agflow/services/agent_generator.py
git commit -m "feat(contracts-v2): génération .sh par opération + .md index par tag + tag descriptions résolues"
```

---

## Task 5 : Frontend — types + dialog tag_overrides

**Files:**
- Modify: `frontend/src/lib/contractsApi.ts`
- Modify: `frontend/src/components/ContractFormDialog.tsx`

- [ ] **Step 5.1 : Ajouter tag_overrides aux types**

Dans `contractsApi.ts` :
- `ContractSummary` : ajouter `tag_overrides: Record<string, string>`, `managed_by_instance: string | null`
- `ContractCreatePayload` : ajouter `tag_overrides?: Record<string, string>`
- `ContractUpdatePayload` : ajouter `tag_overrides?: Record<string, string>`

- [ ] **Step 5.2 : Enrichir ContractFormDialog avec section tag_overrides**

Après le fetch/parse du spec, afficher une section "Descriptions des tags" avec un input texte par tag détecté. Les valeurs modifiées sont sauvegardées dans `tagOverrides` state.

Ajouter un state `tagOverrides: Record<string, string>` initialisé à `{}`. Quand le spec est parsé, pré-remplir chaque champ avec la description du spec. L'utilisateur peut modifier. Les champs modifiés par rapport au spec sont inclus dans le payload `tag_overrides`.

Dans `handleSave()`, ajouter `tag_overrides: tagOverrides` au payload.

- [ ] **Step 5.3 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/contractsApi.ts frontend/src/components/ContractFormDialog.tsx
git commit -m "feat(contracts-v2): tag_overrides éditables dans le dialog + types enrichis"
```

---

## Task 6 : Vérification + déploiement

- [ ] **Step 6.1 : TypeScript strict + ruff**
- [ ] **Step 6.2 : Deploy `bash scripts/deploy.sh --rebuild`**
- [ ] **Step 6.3 : Migration SQL appliquée au démarrage**
- [ ] **Step 6.4 : Test E2E**

1. Supprimer le contrat existant, en recréer un avec fetch
2. Remplir les tag_overrides (descriptions humaines) pour 3-4 tags
3. Sauvegarder → vérifier que les overrides sont persistés
4. Régénérer l'agent → vérifier :
   - `generated/{output_dir}/{slug}/` contient un .md par tag
   - Chaque tag a un sous-répertoire avec des .sh exécutables
   - Les .sh ont shebang, commentaires, usage, curl
   - Les .md listent les opérations avec `@.../{tag}/{OpName}.sh`
   - `prompt.md` utilise les descriptions overridées dans "API disponibles"
5. Exécuter un .sh : `bash ListSecrets.sh` → retourne du JSON

---

## Self-review

- **Couverture spec** : tag_overrides (T1+T3+T5), managed_by_instance (T1+T3, UI hors scope V1 — juste le champ DB+schema), .sh par opération (T2+T4), .md index (T2+T4), operation_to_filename (T2), resolve_tag_description (T2+T4), frontend dialog (T5). ✓
- **Placeholder scan** : T2 step 2.3 dit "code complet dans la spec" — le sous-agent devra lire la spec et le code existant pour implémenter. Acceptable car le generate_operation_script() est détaillé dans la spec. ✓
- **Type consistency** : `tag_overrides: dict[str, str]` cohérent entre schema, service, router, frontend. ✓
- **Hors scope respecté** : managed_by_instance est juste un champ DB/schema, pas d'UI "auto" badge. Pas de sélection de tags/opérations. ✓
