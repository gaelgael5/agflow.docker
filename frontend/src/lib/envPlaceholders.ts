// Matches ${VAR_NAME} *without* a :-default fallback. Variables with a default
// (${VAR:-foo}) always resolve to something, so they aren't worth warning about.
// VAR_NAME starts with a letter or underscore and contains uppercase letters,
// digits, or underscores.
const PLACEHOLDER_RE = /\$\{([A-Z_][A-Z0-9_]*)\}/g;

export function extractPlaceholders(content: string): string[] {
  if (!content) return [];
  const found = new Set<string>();
  for (const m of content.matchAll(PLACEHOLDER_RE)) {
    if (m[1]) found.add(m[1]);
  }
  return [...found];
}
