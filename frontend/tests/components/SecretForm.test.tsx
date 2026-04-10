import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecretForm } from "@/components/SecretForm";
import "@/lib/i18n";

describe("SecretForm", () => {
  it("calls onSubmit with typed values when creating", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();

    render(<SecretForm mode="create" onSubmit={onSubmit} onCancel={onCancel} />);

    await userEvent.type(
      screen.getByPlaceholderText(/ANTHROPIC_API_KEY/),
      "openai_api_key",
    );
    await userEvent.type(
      screen.getByPlaceholderText(/Valeur du secret/),
      "sk-openai",
    );
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));

    expect(onSubmit).toHaveBeenCalledWith({
      var_name: "openai_api_key",
      value: "sk-openai",
      scope: "global",
    });
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();

    render(<SecretForm mode="create" onSubmit={onSubmit} onCancel={onCancel} />);

    await userEvent.click(screen.getByRole("button", { name: /Annuler/ }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("pre-fills name in edit mode and disables it", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();

    render(
      <SecretForm
        mode="edit"
        initialName="ANTHROPIC_API_KEY"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByDisplayValue("ANTHROPIC_API_KEY")).toBeDisabled();

    await userEvent.type(
      screen.getByPlaceholderText(/Valeur du secret/),
      "new-value",
    );
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));

    expect(onSubmit).toHaveBeenCalledWith({
      var_name: "ANTHROPIC_API_KEY",
      value: "new-value",
      scope: "global",
    });
  });
});
