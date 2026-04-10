import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
});
