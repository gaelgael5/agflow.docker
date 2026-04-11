import { describe, it, expect } from "vitest";
import { slugify } from "@/lib/slugify";

describe("slugify", () => {
  it("converts spaces to underscores by default", () => {
    expect(slugify("My Agent")).toBe("my_agent");
    expect(slugify("Docker File")).toBe("docker_file");
  });

  it("lowercases the label", () => {
    expect(slugify("HELLO WORLD")).toBe("hello_world");
  });

  it("strips accents and diacritics", () => {
    expect(slugify("Rôles & Missions")).toBe("roles_missions");
    expect(slugify("Compétences")).toBe("competences");
  });

  it("strips special chars but keeps underscores and dashes", () => {
    expect(slugify("foo-bar_baz (v2)")).toBe("foo-bar_baz_v2");
  });

  it("collapses whitespace runs", () => {
    expect(slugify("a   b   c")).toBe("a_b_c");
  });

  it("trims leading and trailing separators", () => {
    expect(slugify("  hello  ")).toBe("hello");
    expect(slugify("-weird-")).toBe("weird");
  });

  it("uses dash separator when requested", () => {
    expect(slugify("My Agent", "-")).toBe("my-agent");
    expect(slugify("Senior Dev Full Stack", "-")).toBe("senior-dev-full-stack");
  });

  it("returns empty string for empty input", () => {
    expect(slugify("")).toBe("");
    expect(slugify("   ")).toBe("");
  });
});
