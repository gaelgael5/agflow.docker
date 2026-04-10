import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoleSidebar } from "@/components/RoleSidebar";
import type { DocumentSummary } from "@/lib/rolesApi";
import "@/lib/i18n";

function makeDoc(overrides: Partial<DocumentSummary>): DocumentSummary {
  return {
    id: "id1",
    role_id: "r",
    section: "roles",
    parent_path: "",
    name: "doc1",
    content_md: "",
    protected: false,
    created_at: "2026-04-10",
    updated_at: "2026-04-10",
    ...overrides,
  };
}

describe("RoleSidebar", () => {
  it("renders sections with documents", () => {
    const documents = [
      makeDoc({ id: "r1", section: "roles", name: "analyse" }),
      makeDoc({ id: "m1", section: "missions", name: "transform" }),
      makeDoc({ id: "c1", section: "competences", name: "deduction" }),
    ];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    expect(screen.getByText("ROLES")).toBeInTheDocument();
    expect(screen.getByText("MISSIONS")).toBeInTheDocument();
    expect(screen.getByText("COMPETENCES")).toBeInTheDocument();
    expect(screen.getByText("analyse")).toBeInTheDocument();
    expect(screen.getByText("transform")).toBeInTheDocument();
    expect(screen.getByText("deduction")).toBeInTheDocument();
  });

  it("shows 🔒 icon for protected documents", () => {
    const documents = [makeDoc({ id: "p1", name: "locked", protected: true })];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    const row = screen.getByText("locked").closest("button");
    expect(row).toHaveTextContent("🔒");
  });

  it("calls onSelect when a document is clicked", async () => {
    const onSelect = vi.fn();
    const documents = [makeDoc({ id: "click", name: "clickable" })];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={onSelect}
        onAdd={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("clickable"));
    expect(onSelect).toHaveBeenCalledWith("click");
  });

  it("calls onAdd with the section name when Add is clicked", async () => {
    const onAdd = vi.fn();
    render(
      <RoleSidebar
        documents={[]}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={onAdd}
      />,
    );

    const addButtons = screen.getAllByRole("button", { name: /Ajouter/ });
    await userEvent.click(addButtons[0]!);
    expect(onAdd).toHaveBeenCalledWith("roles");
  });
});
