import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RevealButton } from "@/components/RevealButton";
import { secretsApi } from "@/lib/secretsApi";
import "@/lib/i18n";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    reveal: vi.fn(),
  },
}));

describe("RevealButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows masked value by default", () => {
    render(<RevealButton secretId="abc" />);
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Révéler/ })).toBeInTheDocument();
  });

  it("reveals the value after clicking", async () => {
    vi.mocked(secretsApi.reveal).mockResolvedValueOnce({
      id: "abc",
      var_name: "TEST",
      value: "my-secret-value",
    });

    render(<RevealButton secretId="abc" />);
    await userEvent.click(screen.getByRole("button", { name: /Révéler/ }));

    expect(await screen.findByText("my-secret-value")).toBeInTheDocument();
    expect(secretsApi.reveal).toHaveBeenCalledWith("abc");
  });

  it("re-masks after clicking Hide", async () => {
    vi.mocked(secretsApi.reveal).mockResolvedValueOnce({
      id: "abc",
      var_name: "TEST",
      value: "my-secret-value",
    });

    render(<RevealButton secretId="abc" />);
    await userEvent.click(screen.getByRole("button", { name: /Révéler/ }));
    await screen.findByText("my-secret-value");

    await userEvent.click(screen.getByRole("button", { name: /Masquer/ }));
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.queryByText("my-secret-value")).not.toBeInTheDocument();
  });
});
