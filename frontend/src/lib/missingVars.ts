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
