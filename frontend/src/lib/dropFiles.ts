import { slugify } from "@/lib/slugify";

export const MAX_FILE_SIZE_BYTES = 1024 * 1024;

export function isMarkdownFile(file: File): boolean {
  return /\.md$/i.test(file.name);
}

export function sanitizeDocName(filename: string): string {
  const base = filename.replace(/\.md$/i, "");
  return slugify(base, "-");
}

export function findFreeName(candidate: string, existing: readonly string[]): string {
  const taken = new Set(existing);
  if (!taken.has(candidate)) return candidate;
  let i = 2;
  while (taken.has(`${candidate}-${i}`)) i += 1;
  return `${candidate}-${i}`;
}
