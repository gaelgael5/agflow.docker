import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionInstancesTable } from "@/components/supervision/SupervisionInstancesTable";
import type { SupervisedInstance } from "@/lib/supervisionApi";
import type { Filters } from "@/components/supervision/SupervisionFilters";

const mkInstance = (over: Partial<SupervisedInstance> = {}): SupervisedInstance => ({
  id: over.id ?? "11111111-1111-4111-8111-111111111111",
  session_id: "22222222-2222-4222-8222-222222222222",
  agent_id: "claude-code-r1",
  mission: "refactor auth",
  status: "busy",
  last_activity_at: "2026-05-17T10:00:00Z",
  created_at: "2026-05-17T09:00:00Z",
  destroyed_at: null,
  error_message: null,
  last_container_name: "agent-abc",
  ...over,
});

const defaultFilters: Filters = { status: "all", search: "", includeDestroyed: false };

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionInstancesTable", () => {
  it("affiche l'état vide quand instances=[] et isSuccess", () => {
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    expect(screen.getByText(/aucune instance/i)).toBeInTheDocument();
  });

  it("filtre par recherche texte (mission)", () => {
    const a = mkInstance({ id: "a1111111-1111-4111-8111-111111111111", mission: "refactor auth" });
    const b = mkInstance({ id: "b1111111-1111-4111-8111-111111111111", mission: "review PR" });
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[a, b]}
          filters={{ ...defaultFilters, search: "review" }}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    expect(screen.getByText("review PR")).toBeInTheDocument();
    expect(screen.queryByText("refactor auth")).not.toBeInTheDocument();
  });

  it("trie par last_activity_at DESC", () => {
    const a = mkInstance({ id: "a1111111-1111-4111-8111-111111111111", mission: "old", last_activity_at: "2026-05-17T08:00:00Z" });
    const b = mkInstance({ id: "b1111111-1111-4111-8111-111111111111", mission: "new", last_activity_at: "2026-05-17T12:00:00Z" });
    const { container } = render(
      wrap(
        <SupervisionInstancesTable
          instances={[a, b]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0]?.textContent).toContain("new");
    expect(rows[1]?.textContent).toContain("old");
  });

  it("appelle onSelect avec id au clic ligne", () => {
    const onSelect = vi.fn();
    const a = mkInstance({ id: "a1111111-1111-4111-8111-111111111111" });
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[a]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={onSelect}
          onRetry={() => {}}
        />,
      ),
    );
    const row = screen.getByText(/refactor auth/i).closest("tr");
    fireEvent.click(row!);
    expect(onSelect).toHaveBeenCalledWith("a1111111-1111-4111-8111-111111111111");
  });

  it("affiche skeletons quand isLoading=true", () => {
    const { container } = render(
      wrap(
        <SupervisionInstancesTable
          instances={undefined}
          filters={defaultFilters}
          isLoading
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    const skeletons = container.querySelectorAll('[data-skeleton-row]');
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("affiche bloc erreur + bouton retry et appelle onRetry au clic", () => {
    const onRetry = vi.fn();
    render(
      wrap(
        <SupervisionInstancesTable
          instances={undefined}
          filters={defaultFilters}
          isLoading={false}
          error={new Error("boom")}
          onSelect={() => {}}
          onRetry={onRetry}
        />,
      ),
    );
    const btn = screen.getByRole("button", { name: /réessayer|retry/i });
    fireEvent.click(btn);
    expect(onRetry).toHaveBeenCalled();
  });
});
