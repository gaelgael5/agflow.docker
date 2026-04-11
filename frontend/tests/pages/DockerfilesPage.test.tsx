import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DockerfilesPage } from "@/pages/DockerfilesPage";
import { dockerfilesApi } from "@/lib/dockerfilesApi";
import "@/lib/i18n";

vi.mock("@/lib/dockerfilesApi", () => ({
  dockerfilesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    createFile: vi.fn(),
    updateFile: vi.fn(),
    deleteFile: vi.fn(),
    build: vi.fn(),
    getBuild: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DockerfilesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DockerfilesPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders empty state", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun dockerfile/)).toBeInTheDocument();
  });

  it("lists dockerfiles with status badge", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([
      {
        id: "claude-code",
        display_name: "Claude Code",
        description: "",
        parameters: {},
        current_hash: "abc123",
        display_status: "never_built",
        latest_build_id: null,
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText(/Jamais compilé/)).toBeInTheDocument();
  });

  it("keeps file content visible after save (regression M1-B4)", async () => {
    const dockerfile = {
      id: "claude-code",
      display_name: "Claude Code",
      description: "",
      parameters: {},
      current_hash: "abc123",
      display_status: "never_built" as const,
      latest_build_id: null,
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    };
    const initialFile = {
      id: "file-1",
      dockerfile_id: "claude-code",
      path: "Dockerfile",
      content: "",
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    };
    const savedFile = { ...initialFile, content: "FROM python:3.12" };

    vi.mocked(dockerfilesApi.list).mockResolvedValue([dockerfile]);
    // First fetch: file with empty content
    vi.mocked(dockerfilesApi.get)
      .mockResolvedValueOnce({ dockerfile, files: [initialFile] })
      // After save invalidation: refetch returns the saved file
      .mockResolvedValue({ dockerfile, files: [savedFile] });
    vi.mocked(dockerfilesApi.updateFile).mockResolvedValue(savedFile);

    renderPage();

    // Select the dockerfile
    const dockerfileButton = await screen.findByText("Claude Code");
    await userEvent.click(dockerfileButton);

    // Select the file
    const fileButton = await screen.findByText("Dockerfile");
    await userEvent.click(fileButton);

    // Type content into the editor
    const editor = await screen.findByRole("textbox");
    await userEvent.type(editor, "FROM python:3.12");

    // Save
    const saveButton = screen.getByRole("button", { name: /Enregistrer/i });
    await userEvent.click(saveButton);

    // After save, content must still be visible (regression: was becoming empty)
    await waitFor(() => {
      expect(editor).toHaveValue("FROM python:3.12");
    });
  });
});
