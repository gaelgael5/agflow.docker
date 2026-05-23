# Détection et affichage des variables manquantes — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afficher en rouge les variables manquantes (instances et scripts) et indiquer l'origine de chaque valeur, avec auto-fill depuis les variables globales M0.

**Architecture:** Calcul 100% frontend. Trois sources de résolution (globales M0, variables du groupe, sorties des scripts `before` exécutés avant). Logique pure isolée dans `missingVars.ts`, hook React Query `useGroupAvailableVars`, affichage dans `VarRow` et `GroupScriptDialog`.

**Tech Stack:** React 18, TanStack Query, TypeScript strict, Tailwind, i18next, Vitest

---

## Fichiers concernés

| Action | Fichier |
|---|---|
| Créer | `frontend/src/lib/missingVars.ts` |
| Créer | `frontend/src/lib/__tests__/missingVars.test.ts` |
| Créer | `frontend/src/hooks/useGroupAvailableVars.ts` |
| Modifier | `frontend/src/pages/ProjectDetailPage.tsx` |
| Modifier | `frontend/src/i18n/fr.json` |
| Modifier | `frontend/src/i18n/en.json` |

---

## Task 1 : Logique pure `missingVars.ts`

**Files:**
- Create: `frontend/src/lib/missingVars.ts`

- [ ] **Écrire le fichier**

```typescript
// frontend/src/lib/missingVars.ts

export type VarOrigin =
  | "global"        // M0 Secrets & env vars
  | "group"         // Variables du groupe
  | "before_script" // Output d'un script timing=before exécuté avant
  | "manual"        // Valeur littérale saisie manuellement
  | "missing";      // Non résoluble

export interface VarSources {
  globalVarNames: Set<string>;
  groupVarNames: Set<string>;
  beforeOutputNames: Set<string>;
}

/** Extrait les noms de variables référencées dans une valeur type "${VAR}". */
export function extractRefs(value: string): string[] {
  return [...value.matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g)].map((m) => m[1]!);
}

/**
 * Retourne true si la variable est manquante (ne pourra pas être résolue).
 *
 * Règles :
 * 1. varName ∈ n'importe quelle source → pas manquante
 * 2. value vide ET varName ∉ beforeOutputNames → manquante
 * 3. value = "${REF}" ET REF ∉ aucune source → manquante
 * 4. value littérale (pas de ${}) → pas manquante
 */
export function isMissing(
  varName: string,
  value: string | undefined,
  sources: VarSources,
): boolean {
  const { globalVarNames, groupVarNames, beforeOutputNames } = sources;

  // Règle 1 : le nom lui-même est couvert par une source
  if (
    globalVarNames.has(varName) ||
    groupVarNames.has(varName) ||
    beforeOutputNames.has(varName)
  ) {
    return false;
  }

  const v = value?.trim() ?? "";

  // Règle 2 : valeur vide
  if (!v) return true;

  // Règle 4 : valeur littérale (pas de référence ${})
  const refs = extractRefs(v);
  if (refs.length === 0) return false;

  // Règle 3 : au moins une référence non résoluble
  return refs.some(
    (ref) =>
      !globalVarNames.has(ref) &&
      !groupVarNames.has(ref) &&
      !beforeOutputNames.has(ref),
  );
}

/**
 * Retourne l'origine de la valeur d'une variable.
 * Priorité : global > groupe > before_script > manual > missing.
 */
export function getOrigin(
  varName: string,
  value: string | undefined,
  sources: VarSources,
): VarOrigin {
  const { globalVarNames, groupVarNames, beforeOutputNames } = sources;
  const v = value?.trim() ?? "";

  // Si le nom lui-même est couvert
  if (globalVarNames.has(varName)) return "global";
  if (groupVarNames.has(varName)) return "group";
  if (beforeOutputNames.has(varName)) return "before_script";

  if (!v) return "missing";

  const refs = extractRefs(v);
  if (refs.length === 0) return "manual";

  // Cherche la source de la première référence
  const ref = refs[0]!;
  if (globalVarNames.has(ref)) return "global";
  if (groupVarNames.has(ref)) return "group";
  if (beforeOutputNames.has(ref)) return "before_script";

  return "missing";
}
```

- [ ] **Commit**

```bash
git add frontend/src/lib/missingVars.ts
git commit -m "feat(projects): logique pure détection variables manquantes"
```

---

## Task 2 : Tests unitaires `missingVars.test.ts`

**Files:**
- Create: `frontend/src/lib/__tests__/missingVars.test.ts`

- [ ] **Écrire les tests**

```typescript
// frontend/src/lib/__tests__/missingVars.test.ts
import { describe, it, expect } from "vitest";
import { isMissing, getOrigin, type VarSources } from "../missingVars";

const sources: VarSources = {
  globalVarNames: new Set(["GLOBAL_TOKEN"]),
  groupVarNames: new Set(["INTERNAL_URL", "KC_ADMIN_PASSWORD"]),
  beforeOutputNames: new Set(["CLIENT_ID"]),
};

describe("isMissing", () => {
  it("pas manquante si varName dans globalVarNames", () => {
    expect(isMissing("GLOBAL_TOKEN", "", sources)).toBe(false);
  });

  it("pas manquante si varName dans groupVarNames", () => {
    expect(isMissing("INTERNAL_URL", "", sources)).toBe(false);
  });

  it("pas manquante si varName dans beforeOutputNames", () => {
    expect(isMissing("CLIENT_ID", "", sources)).toBe(false);
  });

  it("manquante si valeur vide et varName absent de toutes les sources", () => {
    expect(isMissing("UNKNOWN_VAR", "", sources)).toBe(true);
  });

  it("manquante si valeur vide et undefined", () => {
    expect(isMissing("UNKNOWN_VAR", undefined, sources)).toBe(true);
  });

  it("pas manquante si valeur littérale (pas de ${})", () => {
    expect(isMissing("UNKNOWN_VAR", "http://localhost:3000", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via groupVarNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${INTERNAL_URL}", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via globalVarNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${GLOBAL_TOKEN}", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via beforeOutputNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${CLIENT_ID}", sources)).toBe(false);
  });

  it("manquante si ${REF} non résolvable", () => {
    expect(isMissing("UNKNOWN_VAR", "${MYSTERY_VAR}", sources)).toBe(true);
  });
});

describe("getOrigin", () => {
  it("global si varName dans globalVarNames", () => {
    expect(getOrigin("GLOBAL_TOKEN", "", sources)).toBe("global");
  });

  it("group si varName dans groupVarNames", () => {
    expect(getOrigin("INTERNAL_URL", "http://x", sources)).toBe("group");
  });

  it("before_script si varName dans beforeOutputNames", () => {
    expect(getOrigin("CLIENT_ID", "", sources)).toBe("before_script");
  });

  it("manual si valeur littérale et varName absent", () => {
    expect(getOrigin("UNKNOWN", "http://localhost", sources)).toBe("manual");
  });

  it("missing si valeur vide et varName absent", () => {
    expect(getOrigin("UNKNOWN", "", sources)).toBe("missing");
  });

  it("group si ${REF} pointe vers groupVarNames", () => {
    expect(getOrigin("UNKNOWN", "${INTERNAL_URL}", sources)).toBe("group");
  });

  it("global si ${REF} pointe vers globalVarNames", () => {
    expect(getOrigin("UNKNOWN", "${GLOBAL_TOKEN}", sources)).toBe("global");
  });

  it("missing si ${REF} non résolvable", () => {
    expect(getOrigin("UNKNOWN", "${NOWHERE}", sources)).toBe("missing");
  });
});
```

- [ ] **Lancer les tests**

```bash
cd frontend && npm test -- missingVars
```
Expected: 16 tests PASS

- [ ] **Commit**

```bash
git add frontend/src/lib/__tests__/missingVars.test.ts
git commit -m "test(projects): tests unitaires isMissing et getOrigin"
```

---

## Task 3 : Hook `useGroupAvailableVars`

**Files:**
- Create: `frontend/src/hooks/useGroupAvailableVars.ts`

Ce hook calcule les trois sources disponibles pour un groupe, avec une position optionnelle pour filtrer les scripts `before` exécutés avant la position N.

- [ ] **Écrire le hook**

```typescript
// frontend/src/hooks/useGroupAvailableVars.ts
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { secretsApi } from "@/lib/secretsApi";
import { groupVariablesApi } from "@/lib/groupVariablesApi";
import { groupScriptsApi, scriptsApi } from "@/lib/scriptsApi";
import type { VarSources } from "@/lib/missingVars";

/**
 * Retourne les trois ensembles de noms de variables disponibles pour un groupe.
 *
 * @param groupId   ID du groupe
 * @param upToPosition  Si fourni, ne prend que les scripts before dont position < upToPosition.
 *                      Si absent, prend tous les scripts before (usage instances).
 */
export function useGroupAvailableVars(
  groupId: string,
  upToPosition?: number,
): VarSources {
  const secretsQuery = useQuery({
    queryKey: ["secrets"],
    queryFn: () => secretsApi.list(),
  });
  const groupVarsQuery = useQuery({
    queryKey: ["group-variables", groupId],
    queryFn: () => groupVariablesApi.list(groupId),
  });
  const groupScriptsQuery = useQuery({
    queryKey: ["group-scripts", groupId],
    queryFn: () => groupScriptsApi.list(groupId),
  });
  const allScriptsQuery = useQuery({
    queryKey: ["scripts"],
    queryFn: () => scriptsApi.list(),
  });

  return useMemo(() => {
    const globalVarNames = new Set<string>(
      (secretsQuery.data ?? [])
        .filter((s) => s.has_value)
        .map((s) => s.name),
    );

    const groupVarNames = new Set<string>(
      (groupVarsQuery.data ?? [])
        .filter((v) => v.value.trim() !== "")
        .map((v) => v.name),
    );

    const allScriptsById = new Map(
      (allScriptsQuery.data ?? []).map((s) => [s.id, s]),
    );

    const beforeScripts = (groupScriptsQuery.data ?? []).filter(
      (gs) =>
        gs.timing === "before" &&
        (upToPosition === undefined || gs.position < upToPosition),
    );

    const beforeOutputNames = new Set<string>(
      beforeScripts.flatMap((gs) => {
        const script = allScriptsById.get(gs.script_id);
        return (script?.output_variables ?? []).map((ov) => ov.name);
      }),
    );

    return { globalVarNames, groupVarNames, beforeOutputNames };
  }, [
    secretsQuery.data,
    groupVarsQuery.data,
    groupScriptsQuery.data,
    allScriptsQuery.data,
    upToPosition,
  ]);
}
```

- [ ] **Commit**

```bash
git add frontend/src/hooks/useGroupAvailableVars.ts
git commit -m "feat(projects): hook useGroupAvailableVars"
```

---

## Task 4 : Labels i18n pour les origines

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Ajouter dans `fr.json`** (dans la section `"projects"`) :

```json
"var_origin_global": "Variables globales",
"var_origin_group": "Variables du groupe",
"var_origin_before_script": "Scripts exécutés avant",
"var_origin_manual": "Saisie manuelle"
```

- [ ] **Ajouter dans `en.json`** (dans la section `"projects"`) :

```json
"var_origin_global": "Global variables",
"var_origin_group": "Group variables",
"var_origin_before_script": "Pre-deployment scripts",
"var_origin_manual": "Manual entry"
```

- [ ] **Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(projects): labels i18n origines de variables"
```

---

## Task 5 : Mise à jour de `VarRow` — badge rouge + label d'origine

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (fonction `VarRow`, lignes ~967-1050)

`VarRow` reçoit deux nouvelles props : `sources` (les trois ensembles) et `autoFillValue` (valeur auto-fill depuis M0 si applicable).

- [ ] **Modifier la signature de `VarRow`**

Remplacer :
```typescript
function VarRow({ v, values, statuses, onUpdate, onUpdateStatus, t }: {
  v: ProductVariable;
  values: Record<string, string>;
  statuses: Record<string, InstanceVariableStatus>;
  onUpdate: (name: string, val: string) => void;
  onUpdateStatus: (name: string, status: InstanceVariableStatus) => void;
  t: (key: string, opts?: Record<string, string>) => string;
})
```

Par :
```typescript
function VarRow({ v, values, statuses, sources, onUpdate, onUpdateStatus, t }: {
  v: ProductVariable;
  values: Record<string, string>;
  statuses: Record<string, InstanceVariableStatus>;
  sources: VarSources;
  onUpdate: (name: string, val: string) => void;
  onUpdateStatus: (name: string, status: InstanceVariableStatus) => void;
  t: (key: string, opts?: Record<string, string>) => string;
})
```

- [ ] **Calculer `missing` et `origin` dans le corps de `VarRow`**

Ajouter après la ligne `const displayedSyntax = v.syntax;` :

```typescript
const currentValue = values[v.name] ?? "";
const missing = isMissing(v.name, currentValue, sources);
const origin = getOrigin(v.name, currentValue, sources);
```

- [ ] **Mettre à jour `badgeColorClass`** pour inclure le cas `missing`

Remplacer le bloc `badgeColorClass` existant par :
```typescript
const badgeColorClass = isUndeclared || missing
  ? "border-red-500 text-red-500"
  : isResolved
    ? "border-green-500 text-green-600"
    : v.type === "secret"
      ? "border-orange-400 text-orange-500"
      : "border-blue-400 text-blue-500";
```

- [ ] **Ajouter le label d'origine sous la valeur**

Localiser la zone où la valeur est affichée dans `VarRow` (le champ Input). Après ce champ, ajouter :

```typescript
{!missing && origin !== "missing" && (
  <p className="text-[9px] text-muted-foreground mt-0.5">
    {t(`projects.var_origin_${origin}`)}
  </p>
)}
```

- [ ] **Ajouter les imports nécessaires en tête de fichier** (après les imports existants) :

```typescript
import { isMissing, getOrigin, type VarSources } from "@/lib/missingVars";
```

- [ ] **Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```
Expected : 0 erreur

- [ ] **Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(projects): VarRow — badge rouge + label origine"
```

---

## Task 6 : Auto-fill et passage de `sources` dans `InstanceVariablesDialog`

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (fonction `InstanceVariablesDialog`, lignes ~1040-1210)

- [ ] **Ajouter `useGroupAvailableVars` dans `InstanceVariablesDialog`**

Ajouter au début du corps de la fonction (après les `useState`) :

```typescript
const sources = useGroupAvailableVars(instance.group_id);
```

- [ ] **Auto-fill depuis les variables globales dans `toggle()`**

Dans la fonction `toggle()`, dans la boucle `for (const v of result.variables)`, ajouter avant le `if (v.default)` :

```typescript
// Auto-fill depuis les variables globales M0
if (v.name in merged) continue;
if (sources.globalVarNames.has(v.name)) {
  // La valeur sera fournie automatiquement — on ne préremplit pas manuellement
  continue;
}
```

Note : on ne met pas de valeur dans `merged` pour les vars globales car elles sont résolues à l'exécution. On saute juste pour ne pas les marquer manquantes.

- [ ] **Passer `sources` à chaque `VarRow`**

Aux deux endroits où `VarRow` est rendu (variables et secrets), ajouter la prop `sources={sources}` :

```typescript
<VarRow
  key={v.name}
  v={v}
  values={values}
  statuses={statuses}
  sources={sources}
  onUpdate={updateValue}
  onUpdateStatus={updateStatus}
  t={t}
/>
```

- [ ] **Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```
Expected : 0 erreur

- [ ] **Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(projects): InstanceVariablesDialog — sources disponibles + auto-fill"
```

---

## Task 7 : Variables manquantes dans les inputs des `GroupScriptDialog`

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` (fonction `GroupScriptDialog`, section inputs ~lignes 1879-1920)

- [ ] **Ajouter `useGroupAvailableVars` dans `GroupScriptDialog`**

`GroupScriptDialog` reçoit déjà `groupId` et `initial` (le group_script existant ou null). Ajouter au début du corps :

```typescript
const position = initial?.position ?? 999;
const sources = useGroupAvailableVars(groupId, position);
```

- [ ] **Calculer `missing` et `origin` par input variable**

Dans la boucle `declaredInputs.map((iv) => { ... })` (autour de la ligne 1891), ajouter :

```typescript
const val = inputValues[iv.name] ?? "";
const varMissing = isMissing(iv.name, val, sources);
const origin = getOrigin(iv.name, val, sources);
```

- [ ] **Appliquer la couleur rouge sur le `Label` et l'`Input`**

Remplacer le `Label` et l'`Input` existants par :

```typescript
<Label className={`text-[10px] ${varMissing ? "text-red-500" : ""}`}>
  <span className="font-mono">{iv.name}</span>
  {iv.description && (
    <span className="text-muted-foreground ml-1">— {iv.description}</span>
  )}
</Label>
<div className="flex gap-1 mt-1">
  <div className="flex-1 flex flex-col">
    <Input
      value={inputValues[iv.name] ?? ""}
      onChange={(e) => setInputValues({ ...inputValues, [iv.name]: e.target.value })}
      className={`font-mono text-[11px] ${varMissing ? "border-red-500 focus-visible:ring-red-500" : ""}`}
      placeholder={iv.default || "${ENV_VAR} ou valeur littérale"}
    />
    {!varMissing && origin !== "missing" && (
      <p className="text-[9px] text-muted-foreground mt-0.5">
        {t(`projects.var_origin_${origin}`)}
      </p>
    )}
  </div>
  <select
    value={s}
    onChange={(e) => setInputStatuses({ ...inputStatuses, [iv.name]: e.target.value as InputStatus })}
    className="h-9 text-[11px] rounded-md border border-input bg-background px-2"
    title={t(`scripts.inputs_status_${s}_tooltip`)}
  >
    <option value="keep">{t("scripts.inputs_status_keep")}</option>
    <option value="clean">{t("scripts.inputs_status_clean")}</option>
    <option value="replace">{t("scripts.inputs_status_replace")}</option>
  </select>
</div>
```

- [ ] **Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```
Expected : 0 erreur

- [ ] **Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(projects): GroupScriptDialog — inputs manquants en rouge + origine"
```

---

## Vérification finale

- [ ] Ouvrir `/projects/<id>` avec un groupe ayant des scripts `before` et des instances
- [ ] Vérifier qu'une variable sans source s'affiche en rouge dans l'instance dialog
- [ ] Vérifier que le label d'origine apparaît sous les valeurs résolues
- [ ] Vérifier qu'une variable couverte par une variable du groupe n'est PAS en rouge
- [ ] Vérifier qu'un input de script couvert par un output d'un script before précédent n'est PAS en rouge
- [ ] Lancer tous les tests frontend : `cd frontend && npm test`

---

## Notes techniques

- `useGroupAvailableVars` déduplique les queries : si `useQuery(["secrets"])` est déjà monté ailleurs sur la page, React Query retourne le cache — pas de requête supplémentaire.
- `upToPosition=undefined` couvre le cas instances (tous les before-scripts disponibles).
- `upToPosition=0` couvre le cas d'un nouveau script (aucun before-script avant lui).
- Les labels d'origine n'apparaissent que quand la variable est résolue (`!missing`).
