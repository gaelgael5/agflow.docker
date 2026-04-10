import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import "@/lib/i18n";

describe("BuildStatusBadge", () => {
  it("renders up_to_date", () => {
    render(<BuildStatusBadge status="up_to_date" />);
    expect(screen.getByText(/à jour/)).toBeInTheDocument();
  });

  it("renders never_built", () => {
    render(<BuildStatusBadge status="never_built" />);
    expect(screen.getByText(/Jamais compilé/)).toBeInTheDocument();
  });

  it("renders outdated", () => {
    render(<BuildStatusBadge status="outdated" />);
    expect(screen.getByText(/obsolète/)).toBeInTheDocument();
  });

  it("renders building", () => {
    render(<BuildStatusBadge status="building" />);
    expect(screen.getByText(/Build en cours/)).toBeInTheDocument();
  });

  it("renders failed", () => {
    render(<BuildStatusBadge status="failed" />);
    expect(screen.getByText(/échoué/)).toBeInTheDocument();
  });
});
