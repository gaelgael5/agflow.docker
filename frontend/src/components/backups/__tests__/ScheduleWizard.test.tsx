import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import React from "react";

import i18n from "@/lib/i18n";
import { ScheduleWizard } from "../ScheduleWizard";
import { api } from "@/lib/api";

vi.mock("@/lib/api");

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>{node}</QueryClientProvider>
    </I18nextProvider>,
  );
}

describe("ScheduleWizard", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (api.get as any).mockResolvedValue({
      data: [{ id: "r1", name: "s3-prod", kind: "s3" }],
    });
  });

  it("Step 1 → 2 disabled si pas de recurrence sélectionnée", async () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    const nextBtn = await screen.findByRole("button", { name: /suivant/i });
    expect(nextBtn).toBeDisabled();
  });

  it("Step 1 → 2 activé après choix recurrence", async () => {
    const user = userEvent.setup();
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    await user.click(screen.getByLabelText(/toutes les heures/i));
    expect(screen.getByRole("button", { name: /suivant/i })).not.toBeDisabled();
  });

  it("Step 2 affiche 'À la minute' si hourly choisi", async () => {
    const user = userEvent.setup();
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    await user.click(screen.getByLabelText(/toutes les heures/i));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    expect(screen.getByLabelText(/à la minute/i)).toBeInTheDocument();
  });

  it("Step 3 bouton Save disabled si pas de destination", async () => {
    const user = userEvent.setup();
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    await user.click(screen.getByLabelText(/tous les jours/i));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.clear(screen.getByLabelText(/à l'heure/i));
    await user.type(screen.getByLabelText(/à l'heure/i), "3");
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.type(screen.getByLabelText(/nom/i), "test");
    // Décocher local : aucune remote sélectionnée → invalide
    await user.click(screen.getByLabelText(/conserver une copie locale/i));
    const saveBtn = screen.getByRole("button", { name: /enregistrer/i });
    expect(saveBtn).toBeDisabled();
  });

  it("Step 3 submit avec cron daily généré correctement", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={onSubmit}
      />,
    );
    await user.click(screen.getByLabelText(/tous les jours/i));
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.clear(screen.getByLabelText(/à l'heure/i));
    await user.type(screen.getByLabelText(/à l'heure/i), "3");
    await user.click(screen.getByRole("button", { name: /suivant/i }));
    await user.type(screen.getByLabelText(/nom/i), "db-jour");
    await user.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "db-jour",
          cron_expr: "0 3 * * *",
          keep_local: true,
          remote_connection_ids: [],
        }),
      ),
    );
  });

  it("Mode edit pré-remplit depuis cron '15 * * * *'", async () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="edit"
        initialSchedule={{
          id: "s1",
          name: "db-horaire",
          cron_expr: "15 * * * *",
          remote_connection_ids: ["r1"],
          keep_local: true,
          retention_count: 24,
          enabled: true,
          last_run_at: null,
          last_run_status: null,
          last_run_error: null,
          created_at: "2026-05-20T00:00:00Z",
          updated_at: "2026-05-20T00:00:00Z",
        }}
        onSubmit={async () => {}}
      />,
    );
    await waitFor(() => {
      const hourlyRadio = screen.getByLabelText(/toutes les heures/i) as HTMLInputElement;
      expect(hourlyRadio.checked).toBe(true);
    });
  });

  it("Mode edit cron complexe → fallback affiché", async () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="edit"
        initialSchedule={{
          id: "s1",
          name: "complex",
          cron_expr: "*/15 * * * *",
          remote_connection_ids: [],
          keep_local: true,
          retention_count: 10,
          enabled: true,
          last_run_at: null,
          last_run_status: null,
          last_run_error: null,
          created_at: "2026-05-20T00:00:00Z",
          updated_at: "2026-05-20T00:00:00Z",
        }}
        onSubmit={async () => {}}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/cron personnalisé|cron complexe/i)).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("*/15 * * * *")).toBeInTheDocument();
  });
});
