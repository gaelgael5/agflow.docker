import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionFilters, type Filters } from "@/components/supervision/SupervisionFilters";

const base: Filters = { status: "all", search: "", includeDestroyed: false };

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionFilters", () => {
  it("appelle onChange quand le toggle destroyed est coché", () => {
    const onChange = vi.fn();
    render(wrap(<SupervisionFilters value={base} onChange={onChange} />));
    const checkbox = screen.getByLabelText(/inclure/i) as HTMLInputElement;
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ ...base, includeDestroyed: true });
  });

  it("appelle onChange quand l'input recherche change", () => {
    const onChange = vi.fn();
    render(wrap(<SupervisionFilters value={base} onChange={onChange} />));
    const input = screen.getByPlaceholderText(/mission/i);
    fireEvent.change(input, { target: { value: "refactor" } });
    expect(onChange).toHaveBeenCalledWith({ ...base, search: "refactor" });
  });

  it("affiche le placeholder de recherche", () => {
    render(wrap(<SupervisionFilters value={base} onChange={() => {}} />));
    expect(screen.getByPlaceholderText(/mission/i)).toBeInTheDocument();
  });
});
