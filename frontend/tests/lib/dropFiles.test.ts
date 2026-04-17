import { describe, it, expect } from "vitest";
import {
  isMarkdownFile,
  sanitizeDocName,
  findFreeName,
  MAX_FILE_SIZE_BYTES,
} from "@/lib/dropFiles";

describe("isMarkdownFile", () => {
  it("accepts .md files (case-insensitive)", () => {
    expect(isMarkdownFile(new File([""], "foo.md"))).toBe(true);
    expect(isMarkdownFile(new File([""], "FOO.MD"))).toBe(true);
    expect(isMarkdownFile(new File([""], "Mixed.Md"))).toBe(true);
  });

  it("rejects non-.md extensions", () => {
    expect(isMarkdownFile(new File([""], "foo.txt"))).toBe(false);
    expect(isMarkdownFile(new File([""], "foo.pdf"))).toBe(false);
    expect(isMarkdownFile(new File([""], "foo"))).toBe(false);
    expect(isMarkdownFile(new File([""], "foo.md.backup"))).toBe(false);
  });
});

describe("sanitizeDocName", () => {
  it("strips extension and slugifies", () => {
    expect(sanitizeDocName("Mission Audit.md")).toBe("mission-audit");
    expect(sanitizeDocName("Élève — rôle.md")).toBe("eleve-role");
  });

  it("returns empty string for invalid names", () => {
    expect(sanitizeDocName(".md")).toBe("");
    expect(sanitizeDocName("---.md")).toBe("");
    expect(sanitizeDocName("")).toBe("");
  });

  it("keeps existing hyphens, underscores, and digits", () => {
    expect(sanitizeDocName("mission-v2.md")).toBe("mission-v2");
    expect(sanitizeDocName("step_1.md")).toBe("step_1");
  });
});

describe("findFreeName", () => {
  it("returns the original name when free", () => {
    expect(findFreeName("mission", ["other", "doc"])).toBe("mission");
  });

  it("suffixes -2, -3 until free", () => {
    expect(findFreeName("mission", ["mission"])).toBe("mission-2");
    expect(findFreeName("mission", ["mission", "mission-2"])).toBe("mission-3");
    expect(findFreeName("mission", ["mission", "mission-2", "mission-3"])).toBe("mission-4");
  });
});

describe("MAX_FILE_SIZE_BYTES", () => {
  it("equals 1 MiB", () => {
    expect(MAX_FILE_SIZE_BYTES).toBe(1024 * 1024);
  });
});
