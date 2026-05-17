import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionKpiCards } from "@/components/supervision/SupervisionKpiCards";
import type { SupervisionOverview } from "@/lib/supervisionApi";

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

const baseOverview: SupervisionOverview = {
  sessions: { active: 3, closed: 2, expired: 0 },
  agents: { idle: 5, busy: 2, error: 0, destroyed_total: 8 },
  containers_running: 12,
  mom: { pending: 0, claimed: 3, failed: 0 },
};

describe("SupervisionKpiCards", () => {
  it("affiche les 4 cards avec les bonnes valeurs", () => {
    render(wrap(<SupervisionKpiCards data={baseOverview} />));
    // "3" appears twice (sessions.active + mom.claimed)
    expect(screen.getAllByText("3").length).toBe(2);
    expect(screen.getByText("5")).toBeInTheDocument(); // agents idle
    expect(screen.getByText("12")).toBeInTheDocument(); // containers
    expect(screen.getByText("8")).toBeInTheDocument(); // agents destroyed
    expect(screen.getByText(/Sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/Agents/i)).toBeInTheDocument();
    expect(screen.getByText(/Containers/i)).toBeInTheDocument();
    expect(screen.getByText(/MOM/i)).toBeInTheDocument();
  });

  it("colore les compteurs erreur/failed en destructive quand > 0", () => {
    const overview: SupervisionOverview = {
      ...baseOverview,
      agents: { ...baseOverview.agents, error: 2 },
      mom: { ...baseOverview.mom, failed: 1 },
    };
    const { container } = render(wrap(<SupervisionKpiCards data={overview} />));
    const destructiveEls = container.querySelectorAll(".text-destructive");
    expect(destructiveEls.length).toBeGreaterThanOrEqual(2);
  });

  it("affiche un dash si containers_running est null", () => {
    const overview: SupervisionOverview = {
      ...baseOverview,
      containers_running: null,
    };
    render(wrap(<SupervisionKpiCards data={overview} />));
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("affiche 4 skeletons si data est undefined", () => {
    const { container } = render(wrap(<SupervisionKpiCards data={undefined} />));
    const skeletons = container.querySelectorAll('[role="status"]');
    expect(skeletons.length).toBe(4);
  });
});
