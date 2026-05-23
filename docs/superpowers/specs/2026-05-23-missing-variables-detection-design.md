# Spec : Détection et affichage des variables manquantes

**Date :** 2026-05-23  
**Scope :** `ProjectDetailPage` — instances et scripts du groupe  
**Statut :** Approuvé

---

## Problème

Quand un groupe contient des scripts et des instances, certaines variables attendues (par les recettes ou les scripts) n'ont pas de source résoluble au moment de construire les `.ENV`. L'utilisateur n'a aucun retour visuel sur ce qui manque.

---

## Règles de détection

### Une variable est manquante si :

1. **Valeur vide** et `varName` n'est présente dans aucune source :
   - Variables globales (M0 Secrets & env vars)
   - Variables du groupe
   - Sorties (`output_variables`) des scripts exécutés avant elle

2. **Valeur = `${REF}`** et `REF` n'est présente dans aucune source :
   - Variables globales (M0)
   - Variables du groupe
   - Sorties des scripts exécutés avant elle

### Une variable n'est PAS manquante si :

- `varName` ∈ variables globales → auto-fill de la valeur
- `varName` ∈ variables du groupe
- `varName` ∈ sorties des scripts exécutés avant (même si valeur vide)
- Valeur est une chaîne littérale (pas de `${}`)

---

## Sources disponibles

```
available(N) =
  globalAppVars          (M0 Secrets & env vars de la plateforme)
  ∪ groupVarNames        (variables déclarées dans le groupe)
  ∪ outputVarNames des scripts timing=before avec position < N
```

Pour les **instances** : `available = globalAppVars ∪ groupVarNames ∪ tous les before-script outputs`

---

## Auto-fill

Si `varName ∈ globalAppVars` → la valeur est remplie automatiquement à droite.

---

## Label d'origine (sous chaque valeur)

| Condition | Label affiché |
|---|---|
| `varName` ou `REF` ∈ globalAppVars | *Variables globales* |
| `varName` ou `REF` ∈ groupVarNames | *Variables du groupe* |
| `varName` ou `REF` ∈ before-script outputs | *Scripts exécutés avant* |
| Valeur littérale | *Saisie manuelle* |
| Variable manquante | *(aucun label, badge rouge)* |

Priorité d'affichage : globales > groupe > scripts avant > manuelle.

---

## Affichage

- Variable manquante → badge et label affichés en **rouge**
- Applicable uniformément : instances (`VarRow`) et scripts (inputs du group_script)
- Trigger : React Query — le recalcul se fait automatiquement à chaque invalidation de query (mutation sur group vars, scripts, instances)

---

## Architecture technique

**Calcul frontend uniquement** — toutes les données nécessaires sont présentes dans la page.

### Données nécessaires

| Source | Query existante | Complète ? |
|---|---|---|
| Variables du groupe | `GroupVariablesSection` | ✅ |
| Scripts du groupe (timing, position) | `useQuery(["group-scripts", groupId])` | À vérifier : `output_variables` présentes ? |
| Variables globales M0 | À ajouter | ❌ |
| Sorties des before-scripts | Dépend du point précédent | ❌ |

### Fonction de détection

```typescript
function isMissing(
  varName: string,
  value: string | undefined,
  available: Set<string>
): boolean {
  if (available.has(varName)) return false;
  if (!value?.trim()) return true;
  const refs = [...(value.matchAll(/\$\{([A-Z_a-z][A-Z0-9_a-z]*)\}/g))].map(m => m[1]);
  if (refs.length === 0) return false;
  return refs.some(ref => !available.has(ref));
}
```

### Fonction d'origine

```typescript
type Origin = "global" | "group" | "before_script" | "manual" | "missing";

function getOrigin(varName: string, value: string | undefined, sources: {
  globalVars: Set<string>;
  groupVars: Set<string>;
  beforeOutputs: Set<string>;
}): Origin {
  if (sources.globalVars.has(varName)) return "global";
  if (sources.groupVars.has(varName)) return "group";
  if (sources.beforeOutputs.has(varName)) return "before_script";
  if (!value?.trim()) return "missing";
  const refs = [...(value.matchAll(/\$\{([A-Z_a-z][A-Z0-9_a-z]*)\}/g))].map(m => m[1]);
  if (refs.length === 0) return "manual";
  const ref = refs[0]!;
  if (sources.globalVars.has(ref)) return "global";
  if (sources.groupVars.has(ref)) return "group";
  if (sources.beforeOutputs.has(ref)) return "before_script";
  return "missing";
}
```
