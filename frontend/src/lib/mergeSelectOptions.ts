export interface SelectOption {
  value: string;
  label: string;
}

/**
 * Construit la liste finale d'options pour un <select> dynamique.
 *
 * Algorithme (§2 du contrat) :
 *   1. STATIC_LIST   = staticOptions dans leur ordre manifest
 *   2. DYNAMIC_SORTED = dynamicValues triés alphabétiquement
 *   3. MERGED        = unique(STATIC_LIST ++ DYNAMIC_SORTED), première occurrence gagne
 *   4. Si default défini : déplacer (ou injecter) en tête
 */
export function mergeSelectOptions(
  staticOptions: SelectOption[],
  dynamicValues: string[],
  defaultValue?: string,
): SelectOption[] {
  const staticLabelMap = new Map(staticOptions.map((o) => [o.value, o.label]));

  const dynamicSorted = [...dynamicValues].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" }),
  );

  const seen = new Set<string>();
  const merged: SelectOption[] = [];
  for (const v of [...staticOptions.map((o) => o.value), ...dynamicSorted]) {
    if (!seen.has(v)) {
      seen.add(v);
      merged.push({ value: v, label: staticLabelMap.get(v) ?? v });
    }
  }

  if (defaultValue !== undefined) {
    const idx = merged.findIndex((o) => o.value === defaultValue);
    if (idx > 0) {
      merged.unshift(merged.splice(idx, 1)[0]!);
    } else if (idx === -1) {
      merged.unshift({ value: defaultValue, label: staticLabelMap.get(defaultValue) ?? defaultValue });
    }
  }

  return merged;
}
