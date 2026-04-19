import { slugify } from "@/lib/slugify";

export const MAX_FILE_SIZE_BYTES = 1024 * 1024;

export function isMarkdownFile(file: File): boolean {
  return /\.md$/i.test(file.name);
}

export function sanitizeDocName(filename: string): string {
  const base = filename.replace(/\.md$/i, "");
  return slugify(base, "-");
}

function normalize(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

export function stripSectionPrefix(name: string, section: string): string {
  const norm = normalize(name);
  const candidates = [normalize(section) + "_"];
  if (section.endsWith("s") && section.length > 1) {
    candidates.push(normalize(section.slice(0, -1)) + "_");
  }
  for (const prefix of candidates) {
    if (norm.startsWith(prefix) && norm.length > prefix.length) {
      return name.slice(prefix.length);
    }
  }
  return name;
}

export function findFreeName(candidate: string, existing: readonly string[]): string {
  const taken = new Set(existing);
  if (!taken.has(candidate)) return candidate;
  let i = 2;
  while (taken.has(`${candidate}-${i}`)) i += 1;
  return `${candidate}-${i}`;
}
