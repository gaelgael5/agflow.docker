import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";

import i18n from "@/lib/i18n";
import { RestoreConfirmDialog } from "@/components/RestoreConfirmDialog";

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof RestoreConfirmDialog>> = {},
) {
  const props = {
    open: true,
    filename: "backup-2026-05-14.sql.gz",
    isLoading: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  render(
    <I18nextProvider i18n={i18n}>
      <RestoreConfirmDialog {...props} />
    </I18nextProvider>,
  );
  return props;
}

describe("RestoreConfirmDialog", () => {
  it("disables confirm button until filename is typed exactly", () => {
    renderDialog();
    const confirm = screen.getByRole("button", { name: /confirmer/i });
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText(/nom du fichier/i);
    fireEvent.change(input, { target: { value: "wrong.sql.gz" } });
    expect(confirm).toBeDisabled();

    fireEvent.change(input, {
      target: { value: "backup-2026-05-14.sql.gz" },
    });
    expect(confirm).not.toBeDisabled();
  });

  it("calls onConfirm with the filename when confirm is clicked", () => {
    const { onConfirm } = renderDialog();

    const input = screen.getByLabelText(/nom du fichier/i);
    fireEvent.change(input, {
      target: { value: "backup-2026-05-14.sql.gz" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmer/i }));

    expect(onConfirm).toHaveBeenCalledWith("backup-2026-05-14.sql.gz");
  });

  it("calls onCancel when cancel is clicked", () => {
    const { onCancel } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /annuler/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("disables both buttons during loading", () => {
    renderDialog({ isLoading: true });
    expect(
      screen.getByRole("button", { name: /confirmer/i }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: /annuler/i })).toBeDisabled();
  });
});
