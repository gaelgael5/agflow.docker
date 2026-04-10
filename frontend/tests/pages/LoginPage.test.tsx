import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "@/pages/LoginPage";
import { api } from "@/lib/api";
import "@/lib/i18n";

vi.mock("@/lib/api", () => ({
  api: { post: vi.fn() },
}));

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders form labels in French", () => {
    renderWithRouter();
    expect(screen.getByRole("heading")).toHaveTextContent("Connexion");
    expect(screen.getByLabelText(/Email/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Mot de passe/)).toBeInTheDocument();
  });

  it("submits credentials and stores token on success", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { access_token: "abc.def.ghi" },
    } as never);
    renderWithRouter();
    await userEvent.type(screen.getByLabelText(/Email/), "admin@example.com");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    await waitFor(() => {
      expect(localStorage.getItem("agflow_token")).toBe("abc.def.ghi");
    });
  });

  it("shows error message on failed login", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error("401"));
    renderWithRouter();
    await userEvent.type(screen.getByLabelText(/Email/), "admin@example.com");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Identifiants invalides",
    );
  });
});
