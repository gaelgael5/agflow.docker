/**
 * Derives a slug from a human-readable label:
 * lowercase, whitespace replaced by the separator, and all characters
 * outside [a-z0-9_-] stripped. Accents are best-effort normalized to ASCII.
 *
 * Used to pre-fill identifier fields in creation forms so users type the
 * label first and get a correct-looking slug for free.
 */
export function slugify(label: string, separator: "_" | "-" = "_"): string {
  const sepRegex = new RegExp(`${separator}+`, "g");
  return label
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // strip combining diacritics
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, separator) // non-slug chars (incl. spaces) → sep
    .replace(sepRegex, separator) // collapse runs of the separator
    .replace(/^[_-]+|[_-]+$/g, ""); // trim leading/trailing separators
}
