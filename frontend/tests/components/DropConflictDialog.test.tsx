import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { DropConflictDialog } from "@/components/DropConflictDialog";

function renderDialog(overrides = {}) {
  const props = {
    open: true,
    name: "mission-audit",
    section: "missions",
    suggestedRename: "mission-audit-2",
    onResolve: vi.fn(),
    onOpenChange: vi.fn(),
    ...overrides,
  };
  render(
    <I18nextProvider i18n={i18n}>
      <DropConflictDialog {...props} />
    </I18nextProvider>,
  );
  return props;
}

describe("DropConflictDialog", () => {
  it("renders the conflict message with the doc name and section", () => {
    renderDialog();
    expect(screen.getAllByText(/mission-audit/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/missions/).length).toBeGreaterThan(0);
  });

  it("calls onResolve({action: 'replace', applyToAll: false}) on Replace click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /remplacer|replace/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "replace", applyToAll: false });
  });

  it("calls onResolve({action: 'rename', applyToAll: false}) on Rename click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /renommer|rename/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "rename", applyToAll: false });
  });

  it("calls onResolve({action: 'cancel', applyToAll: false}) on Cancel click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /ignorer|skip/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "cancel", applyToAll: false });
  });

  it("propagates applyToAll=true when the checkbox is checked", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /remplacer|replace/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "replace", applyToAll: true });
  });
});
