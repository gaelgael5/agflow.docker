import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoleSidebar } from "@/components/RoleSidebar";
import type { DocumentSummary, SectionSummary } from "@/lib/rolesApi";
import "@/lib/i18n";

const NATIVE_SECTIONS: SectionSummary[] = [
  { name: "roles", display_name: "Rôles", is_native: true, position: 0 },
  { name: "missions", display_name: "Missions", is_native: true, position: 1 },
  { name: "competences", display_name: "Compétences", is_native: true, position: 2 },
];

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

function renderSidebar(
  props: Partial<React.ComponentProps<typeof RoleSidebar>> = {},
) {
  return render(
    <RoleSidebar
      sections={props.sections ?? NATIVE_SECTIONS}
      documents={props.documents ?? []}
      selectedDocId={props.selectedDocId ?? null}
      onSelect={props.onSelect ?? vi.fn()}
      onAdd={props.onAdd ?? vi.fn()}
      onAddSection={props.onAddSection ?? vi.fn()}
      onDeleteSection={props.onDeleteSection ?? vi.fn()}
      onFilesDropped={props.onFilesDropped}
    />,
  );
}

describe("RoleSidebar", () => {
  it("renders sections with documents", () => {
    const documents = [
      makeDoc({ id: "r1", section: "roles", name: "analyse" }),
      makeDoc({ id: "m1", section: "missions", name: "transform" }),
      makeDoc({ id: "c1", section: "competences", name: "deduction" }),
    ];

    renderSidebar({ documents });

    expect(screen.getByText("Rôles")).toBeInTheDocument();
    expect(screen.getByText("Missions")).toBeInTheDocument();
    expect(screen.getByText("Compétences")).toBeInTheDocument();
    expect(screen.getByText("analyse")).toBeInTheDocument();
    expect(screen.getByText("transform")).toBeInTheDocument();
    expect(screen.getByText("deduction")).toBeInTheDocument();
  });

  it("shows 🔒 icon for protected documents", () => {
    const documents = [makeDoc({ id: "p1", name: "locked", protected: true })];
    renderSidebar({ documents });

    const row = screen.getByText("locked").closest("button");
    expect(row).toHaveTextContent("🔒");
  });

  it("calls onSelect when a document is clicked", async () => {
    const onSelect = vi.fn();
    const documents = [makeDoc({ id: "click", name: "clickable" })];
    renderSidebar({ documents, onSelect });

    await userEvent.click(screen.getByText("clickable"));
    expect(onSelect).toHaveBeenCalledWith("click");
  });

  it("calls onAdd with the section name when + is clicked", async () => {
    const onAdd = vi.fn();
    renderSidebar({ onAdd });

    // Icon buttons expose their purpose via aria-label (i18n key
    // roles.sidebar.add_document → "Ajouter un document")
    const plusButtons = screen.getAllByRole("button", {
      name: /Ajouter un document/i,
    });
    await userEvent.click(plusButtons[0]!);
    expect(onAdd).toHaveBeenCalledWith("roles");
  });

  it("renders custom sections and allows deleting empty ones", async () => {
    const onDeleteSection = vi.fn();
    const sections: SectionSummary[] = [
      ...NATIVE_SECTIONS,
      { name: "outils", display_name: "Outils", is_native: false, position: 3 },
    ];
    renderSidebar({ sections, documents: [], onDeleteSection });

    expect(screen.getByText("Outils")).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole("button", {
      name: /Supprimer cette catégorie/i,
    });
    expect(deleteButtons).toHaveLength(1);
    await userEvent.click(deleteButtons[0]!);
    expect(onDeleteSection).toHaveBeenCalledWith("outils");
  });

  it("hides delete button for native sections", () => {
    renderSidebar({ documents: [] });
    const deleteButtons = screen.queryAllByRole("button", {
      name: /Supprimer cette catégorie/i,
    });
    expect(deleteButtons).toHaveLength(0);
  });

  it("hides delete button for non-empty custom sections", () => {
    const sections: SectionSummary[] = [
      ...NATIVE_SECTIONS,
      { name: "outils", display_name: "Outils", is_native: false, position: 3 },
    ];
    const documents = [
      makeDoc({ id: "t1", section: "outils", name: "vim" }),
    ];
    renderSidebar({ sections, documents });
    const deleteButtons = screen.queryAllByRole("button", { name: "×" });
    expect(deleteButtons).toHaveLength(0);
  });

  it("calls onAddSection when add-section button is clicked", async () => {
    const onAddSection = vi.fn();
    renderSidebar({ onAddSection });
    const button = screen.getByRole("button", { name: /Ajouter une catégorie/i });
    await userEvent.click(button);
    expect(onAddSection).toHaveBeenCalled();
  });

  it("highlights only the section being dragged over", () => {
    const onFilesDropped = vi.fn();
    renderSidebar({ onFilesDropped });
    const missionsZone = screen.getByTestId("section-dropzone-missions");
    fireEvent.dragEnter(missionsZone, {
      dataTransfer: { types: ["Files"], files: [] },
    });
    expect(missionsZone).toHaveClass("ring-2");
    const rolesZone = screen.getByTestId("section-dropzone-roles");
    expect(rolesZone).not.toHaveClass("ring-2");
  });

  it("calls onFilesDropped(sectionName, files) on drop", () => {
    const onFilesDropped = vi.fn();
    renderSidebar({ onFilesDropped });
    const file = new File(["# hello"], "mission.md");
    const missionsZone = screen.getByTestId("section-dropzone-missions");
    fireEvent.drop(missionsZone, {
      dataTransfer: { types: ["Files"], files: [file] },
    });
    expect(onFilesDropped).toHaveBeenCalledWith("missions", [file]);
  });
});
