# Variables d'environnement infra (variante + machine + check projet) — Design

## Objectif

Permettre de déclarer sur chaque **variante typée** (`infra_named_types`) les variables d'environnement attendues, de les remplir sur chaque **machine** qui appartient à cette variante, et d'utiliser ces valeurs au moment de l'exécution des scripts. En V1, l'accent est mis sur la déclaration, la saisie, et la vérification de complétude dans les projets — l'injection runtime est définie mais reportée à V2.

Le flux principal :

```
Variante typée     Machine              Script                Projet
[déclare noms] → [remplit valeurs] → [déclare via_env] → [vérifie complétude]
```

---

## Section 1 — Schéma de base de données

### Migration `121_infra_env_variables.sql`

Deux tables avec FK stricte et `ON DELETE CASCADE` :

```sql
-- Contrat : noms déclarés sur la variante typée
CREATE TABLE infra_named_type_env_vars (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    named_type_id    UUID NOT NULL REFERENCES infra_named_types(id) ON DELETE CASCADE,
    name             VARCHAR(128) NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    position         INT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (named_type_id, name)
);
CREATE INDEX idx_nt_env_vars_named_type ON infra_named_type_env_vars(named_type_id);

-- Implémentation : valeurs saisies sur la machine
CREATE TABLE infra_machine_env_vars (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    machine_id            UUID NOT NULL REFERENCES infra_machines(id) ON DELETE CASCADE,
    named_type_env_var_id UUID NOT NULL REFERENCES infra_named_type_env_vars(id) ON DELETE CASCADE,
    value                 TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (machine_id, named_type_env_var_id)
);
CREATE INDEX idx_machine_env_vars_machine  ON infra_machine_env_vars(machine_id);
CREATE INDEX idx_machine_env_vars_contract ON infra_machine_env_vars(named_type_env_var_id);
```

**Invariants** :
- Une machine ne peut remplir que les variables déclarées par sa variante typée (`named_type_env_var_id` FK → `infra_named_type_env_vars` lui-même FK → `infra_named_types`).
- Supprimer une variante typée ou une machine supprime en cascade toutes ses lignes.
- Supprimer une déclaration de variable (`infra_named_type_env_vars`) supprime en cascade les valeurs renseignées sur toutes les machines.

**Format des valeurs** (colonne `value`) — identique à `group_variables.value` :
- Valeur littérale : `"my-hostname"`
- Référence vault : `"${vault://BACKUPS:PGPASSWORD}"`
- Référence env OS : `"${env://HOME}"`

La résolution est effectuée par `platform_secrets_service.resolve_platform_refs()` déjà en production.

---

## Section 2 — Schemas Pydantic + Interfaces TypeScript + API REST

### 2.1 Schemas Pydantic

**Fichier** : `backend/src/agflow/schemas/infra_env_vars.py`

```python
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"

class NamedTypeEnvVarRow(BaseModel):
    id: UUID
    named_type_id: UUID
    name: str
    description: str = ""
    position: int = 0
    created_at: datetime
    updated_at: datetime

class NamedTypeEnvVarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=_NAME_RE)
    description: str = ""
    position: int = 0

class NamedTypeEnvVarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128, pattern=_NAME_RE)
    description: str | None = None
    position: int | None = None

class MachineEnvVarRow(BaseModel):
    """Vue dénormalisée : inclut name + description du contrat."""
    id: UUID
    machine_id: UUID
    named_type_env_var_id: UUID
    name: str
    description: str
    value: str
    created_at: datetime
    updated_at: datetime

class MachineEnvVarUpsert(BaseModel):
    """Upsert atomique : dict {named_type_env_var_id → value}."""
    values: dict[UUID, str]
```

### 2.2 Interfaces TypeScript

**Fichier** : `frontend/src/lib/infraEnvVarsApi.ts` (nouveau)

```typescript
export interface NamedTypeEnvVar {
  id: string;
  named_type_id: string;
  name: string;
  description: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface NamedTypeEnvVarCreate {
  name: string;
  description?: string;
  position?: number;
}

export interface NamedTypeEnvVarUpdate {
  name?: string;
  description?: string;
  position?: number;
}

export interface MachineEnvVar {
  id: string;
  machine_id: string;
  named_type_env_var_id: string;
  name: string;
  description: string;
  value: string;
  created_at: string;
  updated_at: string;
}

export interface MachineEnvVarUpsert {
  values: Record<string, string>; // named_type_env_var_id → value
}

export interface ProjectEnvVarsCheckMissing {
  group_script_id: string;
  script_id: string;
  script_name: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string | null;
  target_kind: string;
  missing_env_vars: string[];
}

export interface ProjectEnvVarsCheck {
  project_id: string;
  total_missing: number;
  items: ProjectEnvVarsCheckMissing[];
}
```

### 2.3 Endpoints REST

**Variante typée — CRUD des déclarations** (router : `api/admin/infra_named_types.py`) :

| Méthode | URL | Corps | Réponse |
|---------|-----|-------|---------|
| GET | `/api/infra/named-types/{id}/env-vars` | — | `list[NamedTypeEnvVarRow]` |
| POST | `/api/infra/named-types/{id}/env-vars` | `NamedTypeEnvVarCreate` | `NamedTypeEnvVarRow` |
| PUT | `/api/infra/named-types/{id}/env-vars/{ev_id}` | `NamedTypeEnvVarUpdate` | `NamedTypeEnvVarRow` |
| DELETE | `/api/infra/named-types/{id}/env-vars/{ev_id}` | — | `204` |

**Machine — saisie des valeurs** (router : `api/admin/infra_machines.py`) :

| Méthode | URL | Corps | Réponse |
|---------|-----|-------|---------|
| GET | `/api/infra/machines/{id}/env-vars` | — | `list[MachineEnvVarRow]` |
| PUT | `/api/infra/machines/{id}/env-vars` | `MachineEnvVarUpsert` | `list[MachineEnvVarRow]` |

Le GET renvoie **toutes** les variables déclarées par la variante typée de la machine, avec `value = ""` pour celles non encore remplies (join LEFT).

Le PUT est un **upsert atomique en transaction** : INSERT ON CONFLICT DO UPDATE pour chaque entrée du dict. Les variables absentes du dict ne sont pas modifiées. Les IDs non reconnus (n'appartenant pas à la variante de la machine) lèvent une 422.

**Check projet** (router : `api/admin/projects.py`) :

| Méthode | URL | Réponse |
|---------|-----|---------|
| GET | `/api/admin/projects/{project_id}/env-vars-check` | `ProjectEnvVarsCheck` |

L'algorithme :
1. Charger tous les `group_scripts` du projet avec `via_env=True` dans leurs `input_variables`.
2. Pour chaque `group_script`, déterminer la machine cible (machine_id direct ou deployment_host du projet).
3. Charger les env vars de la machine → dict `{name: resolved_value}`.
4. Pour chaque variable `via_env=True` du script, vérifier qu'elle figure dans le dict avec une valeur non vide.
5. Retourner les carences.

---

## Section 3 — UX

### 3.1 Variante typée — dialog d'édition

Dans `InfraNamedTypesPage.tsx`, le dialog d'édition d'une variante typée reçoit un **onglet supplémentaire** "Env vars" (ou une section collapsible si la UI existante n'utilise pas d'onglets).

Composant : `NamedTypeEnvVarsSection`

- Liste des variables déclarées : colonnes nom / description / position / actions (éditer, supprimer).
- Bouton "Ajouter" → ligne en édition inline (nom obligatoire, validé regex `^[A-Za-z_][A-Za-z0-9_]*$`, max 128 chars).
- Suppression → Dialog de confirmation (pattern shadcn, jamais `window.confirm`).
- Réordonnancement : champ `position` numérique, pas de drag-and-drop en V1.

### 3.2 Machine — dialog d'édition

Dans `InfraMachinesPage.tsx`, le dialog d'édition d'une machine reçoit une **section** "Variables d'environnement" conditionnelle : affichée uniquement si la variante typée de la machine a au moins une variable déclarée.

Composant : `MachineEnvVarsSection`

- Liste les variables issues du contrat (GET `/api/infra/machines/{id}/env-vars`).
- Pour chaque variable : label nom + description + champ texte pour la valeur.
- Indicateur `StatusIndicator` par ligne :
  - 🔴 Rouge : valeur vide
  - 🟠 Orange : valeur non vide mais contient une référence non résolue (détection client-side : `${` présent)
  - 🟢 Vert : valeur non vide et aucune référence détectée
- Bouton "Enregistrer" → PUT `/api/infra/machines/{id}/env-vars` avec toutes les valeurs courantes.
- La saisie supporte les références littérales `${vault://...}` et `${env://...}` (pas d'auto-complétion en V1).

### 3.3 Projet — bannière de complétude

Dans la page projet (ou son composant de synthèse), une bannière/badge "X variable(s) manquante(s)" est affichée si `total_missing > 0`, en utilisant les données du hook `useProjectEnvVarsCheck(projectId)`.

- Badge rouge sur l'onglet ou la carte projet si `total_missing > 0`.
- Tooltip ou section détail : liste les scripts concernés et les noms des variables manquantes.
- Invalidation React Query : `['projects', projectId, 'env-vars-check']` — invalidé quand les machine env vars changent.

---

## Section 4 — Check projet (`/env-vars-check`)

### Algorithme de vérification

```python
async def check_project_env_vars(project_id: UUID) -> ProjectEnvVarsCheck:
    # 1. Récupérer tous les group_scripts du projet
    # 2. Pour chaque group_script, charger le script complet (input_variables)
    # 3. Filtrer les input_variables où via_env=True
    # 4. Résoudre la machine cible (machine_id direct ou deployment_host du projet)
    # 5. Charger resolve_for_machine(machine_id) → dict {name: resolved_value}
    # 6. Comparer : variables via_env du script absentes du dict ou valeur vide = manquante
    # 7. Construire ProjectEnvVarsCheck
```

### Schemas de réponse

```python
class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str        # "fixed_machine" | "deployment_host"
    missing_env_vars: list[str]

class ProjectEnvVarsCheck(BaseModel):
    project_id: UUID
    total_missing: int
    items: list[ProjectEnvVarsCheckMissing]
```

---

## Section 5 — Résolution runtime

### Service `infra_env_vars_service.resolve_for_machine`

```python
async def resolve_for_machine(machine_id: UUID) -> dict[str, str]:
    """
    Retourne {name: valeur_résolue} pour toutes les env vars d'une machine.
    Les entrées avec valeur vide après résolution sont exclues.
    Résout ${vault://...} et ${env://...} via platform_secrets_service.
    """
    secrets_map = await platform_secrets_service.resolve_all()
    rows = await list_machine_env_vars(machine_id)  # inclut value="" pour non remplies
    result: dict[str, str] = {}
    for row in rows:
        resolved = platform_secrets_service.resolve_platform_refs(row.value, secrets_map)
        if resolved:
            result[row.name] = resolved
    return result
```

### Périmètre V1 / V2

**V1 (ce chantier)** :
- Tables + migration SQL
- Services backend (CRUD + upsert + resolve_for_machine + check_project)
- API REST (6 endpoints)
- UI variante typée (déclaration)
- UI machine (saisie)
- UI projet (bannière + détail manquants)
- Tests backend + frontend

**V2 (déféré — hors scope)** :
- Injection effective dans le runner de scripts au moment de l'exécution.
- La priorité d'injection sera : machine env vars (basse) < group_variables (existant) < group_script.input_values (haute).
- Le hook d'injection sera dans `scripts_runner_service` quand il sera créé.

---

## Section 6 — Tests et gestion d'erreurs

### Tests backend

**Fichier** : `backend/tests/services/test_infra_env_vars_service.py`

- `test_crud_named_type_env_vars` : create / list / update / delete sur une variante typée de fixture.
- `test_unique_constraint` : deux variables même nom sur même variante → IntegrityError.
- `test_cascade_delete_named_type` : supprimer la variante supprime les env vars déclarées.
- `test_machine_upsert_basic` : PUT avec 2 valeurs → GET retourne les 2.
- `test_machine_upsert_idempotent` : PUT deux fois → pas de doublon.
- `test_machine_upsert_invalid_id` : PUT avec un ID appartenant à une autre variante → 422.
- `test_cascade_delete_machine` : supprimer la machine supprime les valeurs.
- `test_resolve_for_machine` : valeur littérale, valeur `${vault://...}` (mock), valeur vide exclue.
- `test_check_project_no_missing` : projet avec scripts via_env et toutes les machines complètes → `total_missing=0`.
- `test_check_project_with_missing` : une variable vide → apparaît dans `items`.

**Fichier** : `backend/tests/api/test_infra_env_vars_api.py`

- Tests HTTP pour les 6 endpoints (200, 201, 204, 404, 422).

### Tests frontend

**Fichier** : `frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx`

- Render liste vide → affiche message vide.
- Ajouter une variable → POST appelé, liste mise à jour.
- Supprimer → Dialog de confirmation affiché, DELETE après confirmation.

**Fichier** : `frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx`

- Variables chargées → affichées avec bon `StatusIndicator`.
- Modification valeur + Enregistrer → PUT appelé avec les bonnes valeurs.

### Gestion d'erreurs

| Scénario | Comportement |
|----------|-------------|
| Nom invalide (regex) | 422 backend + message validation i18n côté UI |
| Doublon de nom | 409 ou 422 (constraint) + toast erreur |
| ID env var inconnu dans upsert | 422 avec détail |
| Machine sans variante typée | Section env vars masquée côté UI |
| Machine avec variante sans vars déclarées | Section masquée ou message "aucune variable déclarée" |
| Suppression d'une variable avec des valeurs machine | CASCADE automatique, avertissement dans le Dialog de confirmation |

---

## Fichiers à créer / modifier

### Backend
| Action | Fichier |
|--------|---------|
| Créer | `backend/migrations/121_infra_env_variables.sql` |
| Créer | `backend/src/agflow/schemas/infra_env_vars.py` |
| Créer | `backend/src/agflow/services/infra_env_vars_service.py` |
| Modifier | `backend/src/agflow/api/admin/infra_named_types.py` — 4 endpoints |
| Modifier | `backend/src/agflow/api/admin/infra_machines.py` — 2 endpoints |
| Modifier | `backend/src/agflow/api/admin/projects.py` — 1 endpoint check |
| Créer | `backend/tests/services/test_infra_env_vars_service.py` |
| Créer | `backend/tests/api/test_infra_env_vars_api.py` |

### Frontend
| Action | Fichier |
|--------|---------|
| Créer | `frontend/src/lib/infraEnvVarsApi.ts` |
| Créer | `frontend/src/hooks/useInfraEnvVars.ts` |
| Créer | `frontend/src/components/NamedTypeEnvVarsSection.tsx` |
| Créer | `frontend/src/components/MachineEnvVarsSection.tsx` |
| Modifier | `frontend/src/pages/InfraNamedTypesPage.tsx` — intégrer section |
| Modifier | `frontend/src/pages/InfraMachinesPage.tsx` — intégrer section |
| Modifier | `frontend/src/pages/ProjectsPage.tsx` (ou composant projet) — bannière check |
| Modifier | `frontend/src/i18n/fr.json` + `en.json` — clés env vars |
| Créer | `frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx` |
| Créer | `frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx` |

---

## Dépendances et ordre d'implémentation

```
Migration SQL
  → Schemas Pydantic
    → Services backend (CRUD + upsert + resolve_for_machine)
      → Tests services
      → API endpoints
        → Tests API
  → Interfaces TypeScript + infraEnvVarsApi.ts
    → hooks useInfraEnvVars.ts
      → NamedTypeEnvVarsSection + tests
      → MachineEnvVarsSection + tests
      → Intégration pages
      → Bannière projet
  → i18n FR + EN
```

---

*Design validé le 2026-05-21. V1 = déclaration + saisie + check projet. Injection runtime = V2.*
