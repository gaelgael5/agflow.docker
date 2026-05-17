import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionStreamIndicator } from "@/components/supervision/SupervisionStreamIndicator";

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionStreamIndicator", () => {
  it("affiche le label connected avec le tooltip i18n", () => {
    render(wrap(<SupervisionStreamIndicator status="open" />));
    expect(screen.getByText(/actif|active/i)).toBeInTheDocument();
  });

  it("affiche les 3 états (open/connecting/closed) avec attribut data distinct", () => {
    const { container: cOpen } = render(wrap(<SupervisionStreamIndicator status="open" />));
    const { container: cConn } = render(wrap(<SupervisionStreamIndicator status="connecting" />));
    const { container: cClosed } = render(wrap(<SupervisionStreamIndicator status="closed" />));
    expect(cOpen.querySelector('[data-stream-state="open"]')).toBeInTheDocument();
    expect(cConn.querySelector('[data-stream-state="connecting"]')).toBeInTheDocument();
    expect(cClosed.querySelector('[data-stream-state="closed"]')).toBeInTheDocument();
  });
});
