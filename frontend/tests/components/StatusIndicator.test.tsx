import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusIndicator } from "@/components/StatusIndicator";
import "@/lib/i18n";

describe("StatusIndicator", () => {
  it("renders red dot when status is missing", () => {
    render(<StatusIndicator status="missing" label="TEST_VAR" />);
    const el = screen.getByRole("img", { name: /TEST_VAR/ });
    expect(el).toHaveTextContent("🔴");
  });

  it("renders orange dot when status is empty", () => {
    render(<StatusIndicator status="empty" label="TEST_VAR" />);
    const el = screen.getByRole("img", { name: /TEST_VAR/ });
    expect(el).toHaveTextContent("🟠");
  });

  it("renders green dot when status is ok", () => {
    render(<StatusIndicator status="ok" label="TEST_VAR" />);
    const el = screen.getByRole("img", { name: /TEST_VAR/ });
    expect(el).toHaveTextContent("🟢");
  });
});
