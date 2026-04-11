import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import "@/lib/i18n";

describe("EnvVarStatus", () => {
  it("renders red dot with destructive variant when missing", () => {
    render(<EnvVarStatus name="ANTHROPIC_API_KEY" status="missing" />);
    const badge = screen.getByText("ANTHROPIC_API_KEY").closest("div");
    expect(badge).toHaveAttribute(
      "title",
      "ANTHROPIC_API_KEY — Variable manquante",
    );
    expect(badge?.className).toContain("red");
  });

  it("renders amber dot when empty", () => {
    render(<EnvVarStatus name="FOO" status="empty" />);
    const badge = screen.getByText("FOO").closest("div");
    expect(badge).toHaveAttribute(
      "title",
      "FOO — Variable présente mais vide",
    );
    expect(badge?.className).toContain("amber");
  });

  it("renders green dot when ok", () => {
    render(<EnvVarStatus name="BAR" status="ok" />);
    const badge = screen.getByText("BAR").closest("div");
    expect(badge).toHaveAttribute("title", "BAR — Variable renseignée");
    expect(badge?.className).toContain("emerald");
  });

  it("falls back to missing when status is undefined (loading)", () => {
    render(<EnvVarStatus name="LOADING" status={undefined} />);
    expect(screen.getByText("LOADING")).toBeInTheDocument();
  });

  it("renders compact layout with dot + name only when compact", () => {
    render(<EnvVarStatus name="X" status="ok" compact />);
    const span = screen.getByText("X").closest("span");
    expect(span?.className).toContain("font-mono");
    // Not a Badge pill — no rounded-full wrapper from Badge variant classes
    expect(span?.className).not.toContain("rounded-full");
  });
});
