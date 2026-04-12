/**
 * Tiny regex-based syntax highlighter for the file editor overlay.
 * Avoids pulling a full Prism / Shiki / CodeMirror dependency.
 *
 * Each highlighter returns a flat list of { text, cls } tokens that the
 * caller renders as coloured <span>s inside a <pre>.
 */

export interface Token {
  text: string;
  cls: string;
}

export type Language = "dockerfile" | "bash" | "json" | "plain";

export function detectLanguage(path: string): Language {
  const lower = path.toLowerCase();
  if (lower === "dockerfile" || lower.endsWith(".dockerfile")) {
    return "dockerfile";
  }
  if (lower.endsWith(".sh") || lower === "entrypoint.sh") return "bash";
  if (lower.endsWith(".json")) return "json";
  return "plain";
}

export function highlight(source: string, language: Language): Token[] {
  switch (language) {
    case "dockerfile":
      return highlightDockerfile(source);
    case "bash":
      return highlightBash(source);
    case "json":
      return highlightJson(source);
    case "plain":
    default:
      return [{ text: source, cls: "" }];
  }
}

// ─────────────────────────────────────────────────────────────
// Dockerfile
// ─────────────────────────────────────────────────────────────

const DOCKERFILE_INSTRUCTIONS = new Set([
  "FROM",
  "RUN",
  "CMD",
  "LABEL",
  "MAINTAINER",
  "EXPOSE",
  "ENV",
  "ADD",
  "COPY",
  "ENTRYPOINT",
  "VOLUME",
  "USER",
  "WORKDIR",
  "ARG",
  "ONBUILD",
  "STOPSIGNAL",
  "HEALTHCHECK",
  "SHELL",
  "AS",
]);

export function highlightDockerfile(source: string): Token[] {
  const out: Token[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    tokenizeDockerfileLine(line, out);
    if (i < lines.length - 1) out.push({ text: "\n", cls: "" });
  }
  return out;
}

function tokenizeDockerfileLine(line: string, out: Token[]): void {
  // Preserve leading whitespace
  const leadingMatch = line.match(/^\s*/);
  const leading = leadingMatch ? leadingMatch[0] : "";
  if (leading) out.push({ text: leading, cls: "" });

  const trimmed = line.slice(leading.length);
  if (!trimmed) return;

  // Full-line comment
  if (trimmed.startsWith("#")) {
    out.push({ text: trimmed, cls: "text-zinc-500 italic" });
    return;
  }

  // Instruction at start of line: FROM, RUN, COPY, etc.
  const instrMatch = trimmed.match(/^([A-Z][A-Z0-9]*)\b(\s*)/);
  if (instrMatch && DOCKERFILE_INSTRUCTIONS.has(instrMatch[1]!)) {
    out.push({
      text: instrMatch[1]!,
      cls: "text-pink-400 font-semibold",
    });
    if (instrMatch[2]) out.push({ text: instrMatch[2], cls: "" });
    tokenizeDockerfileArgs(trimmed.slice(instrMatch[0].length), out);
    return;
  }

  tokenizeDockerfileArgs(trimmed, out);
}

function tokenizeDockerfileArgs(rest: string, out: Token[]): void {
  // After the instruction, handle strings, variables, flags, and trailing
  // comments. This is the same grammar we use for bash args (close enough).
  const pattern =
    /("(?:\\.|[^"\\])*")|('(?:\\.|[^'\\])*')|(#.*$)|(--?[a-zA-Z][\w.-]*(?:=[^\s]*)?)|(\$\{[^}]*\}|\$\w+)|(\s+)|([^\s"'$#\\-]+)|(\\$)|(\\)|([\s\S])/g;
  for (const m of rest.matchAll(pattern)) {
    if (m[1] !== undefined) out.push({ text: m[1], cls: "text-amber-300" });
    else if (m[2] !== undefined)
      out.push({ text: m[2], cls: "text-amber-300" });
    else if (m[3] !== undefined)
      out.push({ text: m[3], cls: "text-zinc-500 italic" });
    else if (m[4] !== undefined)
      out.push({ text: m[4], cls: "text-cyan-300" });
    else if (m[5] !== undefined)
      out.push({ text: m[5], cls: "text-violet-300" });
    else if (m[6] !== undefined) out.push({ text: m[6], cls: "" });
    else if (m[7] !== undefined) out.push({ text: m[7], cls: "text-zinc-100" });
    else if (m[8] !== undefined)
      out.push({ text: m[8], cls: "text-zinc-500" });
    else if (m[9] !== undefined)
      out.push({ text: m[9], cls: "text-zinc-500" });
    else if (m[10] !== undefined) out.push({ text: m[10], cls: "" });
  }
}

// ─────────────────────────────────────────────────────────────
// Bash
// ─────────────────────────────────────────────────────────────

const BASH_KEYWORDS = new Set([
  "if",
  "then",
  "else",
  "elif",
  "fi",
  "for",
  "while",
  "until",
  "do",
  "done",
  "case",
  "esac",
  "in",
  "function",
  "return",
  "exit",
  "break",
  "continue",
  "local",
  "readonly",
  "declare",
  "export",
  "unset",
  "set",
  "shift",
  "trap",
  "source",
  "eval",
  "exec",
  "true",
  "false",
  "test",
]);

const BASH_BUILTINS = new Set([
  "echo",
  "printf",
  "read",
  "cd",
  "pwd",
  "pushd",
  "popd",
  "alias",
  "unalias",
  "type",
  "command",
  "builtin",
  "kill",
  "wait",
  "jobs",
  "bg",
  "fg",
  "umask",
  "ulimit",
  "getopts",
]);

export function highlightBash(source: string): Token[] {
  const out: Token[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    tokenizeBashLine(lines[i]!, out);
    if (i < lines.length - 1) out.push({ text: "\n", cls: "" });
  }
  return out;
}

function tokenizeBashLine(line: string, out: Token[]): void {
  // Shebang
  if (line.startsWith("#!")) {
    out.push({ text: line, cls: "text-pink-400 italic" });
    return;
  }
  // Leading whitespace
  const leadingMatch = line.match(/^\s*/);
  const leading = leadingMatch ? leadingMatch[0] : "";
  if (leading) out.push({ text: leading, cls: "" });

  const trimmed = line.slice(leading.length);
  if (!trimmed) return;

  // Full-line comment
  if (trimmed.startsWith("#")) {
    out.push({ text: trimmed, cls: "text-zinc-500 italic" });
    return;
  }

  const pattern =
    /("(?:\\.|[^"\\])*")|('(?:\\.|[^'\\])*')|(#.*$)|(--?[a-zA-Z][\w.-]*(?:=[^\s]*)?)|(\$\{[^}]*\}|\$\w+|\$[@*#?$!0-9])|(\s+)|([a-zA-Z_][\w]*)|(\d+)|(\\$)|([\s\S])/g;
  let atLineStart = true;
  for (const m of trimmed.matchAll(pattern)) {
    if (m[1] !== undefined) {
      out.push({ text: m[1], cls: "text-amber-300" });
      atLineStart = false;
    } else if (m[2] !== undefined) {
      out.push({ text: m[2], cls: "text-amber-300" });
      atLineStart = false;
    } else if (m[3] !== undefined) {
      out.push({ text: m[3], cls: "text-zinc-500 italic" });
    } else if (m[4] !== undefined) {
      out.push({ text: m[4], cls: "text-cyan-300" });
      atLineStart = false;
    } else if (m[5] !== undefined) {
      out.push({ text: m[5], cls: "text-violet-300" });
      atLineStart = false;
    } else if (m[6] !== undefined) {
      out.push({ text: m[6], cls: "" });
    } else if (m[7] !== undefined) {
      const word = m[7];
      if (BASH_KEYWORDS.has(word)) {
        out.push({ text: word, cls: "text-pink-400 font-semibold" });
      } else if (atLineStart && BASH_BUILTINS.has(word)) {
        out.push({ text: word, cls: "text-emerald-300 font-semibold" });
      } else if (atLineStart) {
        out.push({ text: word, cls: "text-emerald-300" });
      } else {
        out.push({ text: word, cls: "text-zinc-100" });
      }
      atLineStart = false;
    } else if (m[8] !== undefined) {
      out.push({ text: m[8], cls: "text-orange-300" });
      atLineStart = false;
    } else if (m[9] !== undefined) {
      out.push({ text: m[9], cls: "text-zinc-500" });
    } else if (m[10] !== undefined) {
      out.push({ text: m[10], cls: "" });
    }
  }
}

// ─────────────────────────────────────────────────────────────
// JSON
// ─────────────────────────────────────────────────────────────

export function highlightJson(source: string): Token[] {
  const out: Token[] = [];
  // Single global regex: strings (detect if followed by :), numbers, keywords, punctuation, whitespace, other.
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b|\bnull\b)|([{}[\],])|(\s+)|([\s\S])/g;
  for (const m of source.matchAll(pattern)) {
    if (m[1] !== undefined) {
      // Key vs value: key has trailing colon captured in group 2
      if (m[2] !== undefined) {
        out.push({ text: m[1], cls: "text-cyan-300" });
        out.push({ text: m[2], cls: "text-zinc-400" });
      } else {
        out.push({ text: m[1], cls: "text-amber-300" });
      }
    } else if (m[3] !== undefined) {
      out.push({ text: m[3], cls: "text-orange-300" });
    } else if (m[4] !== undefined) {
      out.push({ text: m[4], cls: "text-violet-300" });
    } else if (m[5] !== undefined) {
      out.push({ text: m[5], cls: "text-zinc-400" });
    } else if (m[6] !== undefined) {
      out.push({ text: m[6], cls: "" });
    } else if (m[7] !== undefined) {
      out.push({ text: m[7], cls: "" });
    }
  }
  return out;
}
