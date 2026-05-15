import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/lib/backupsApi", () => ({
  backupsApi: {
    listLocal: vi.fn().mockResolvedValue([]),
    listRemoteFiles: vi.fn().mockResolvedValue([]),
    pullFromRemote: vi.fn(),
    restoreLocal: vi.fn(),
  },
}));

import i18n from "@/lib/i18n";
import { BackupsPage } from "@/pages/BackupsPage";

describe("BackupsPage", () => {
  it("renders title + both sections (local + remote)", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <BackupsPage />
        </QueryClientProvider>
      </I18nextProvider>,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: /sauvegardes/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /sauvegardes locales/i,
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /sauvegardes distantes/i,
      }),
    ).toBeInTheDocument();
  });
});
