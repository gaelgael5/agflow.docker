import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "@/components/layout/TopBar";
import "@/lib/i18n";

// Helper to set/clear the JWT used by useAuth().
function setToken(role: "admin" | "operator" | "viewer" | null): void {
  if (role === null) {
    localStorage.removeItem("agflow_token");
    return;
  }
  // unsigned JWT — useAuth only reads the payload via atob(), no verification
  const payload = btoa(JSON.stringify({ role, sub: "test@example.com" }));
  localStorage.setItem("agflow_token", `header.${payload}.sig`);
}

// Mock the api module — actual axios import is replaced.
vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/lib/api";

describe("TopBar — Export button", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    setToken(null);
  });

  it("renders the export button when user is admin", () => {
    setToken("admin");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/Exporter|Export/i)).toBeInTheDocument();
  });

  it("does NOT render the export button when user is operator", () => {
    setToken("operator");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/Exporter|Export/i)).toBeNull();
  });

  it("does NOT render the export button when user is viewer", () => {
    setToken("viewer");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/Exporter|Export/i)).toBeNull();
  });

  it("triggers a blob download when admin clicks the button", async () => {
    setToken("admin");
    const blob = new Blob(["zip-bytes"], { type: "application/zip" });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: blob,
      headers: {
        "content-disposition": 'attachment; filename="agflow-data-20260429-141500.zip"',
      },
    });

    const clickSpy = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") {
        el.click = clickSpy;
      }
      return el;
    });

    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByLabelText(/Exporter|Export/i));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/admin/system/export", {
        responseType: "blob",
      });
    });
    expect(clickSpy).toHaveBeenCalled();
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });
});
