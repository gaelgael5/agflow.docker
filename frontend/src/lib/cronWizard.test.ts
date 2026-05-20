import { describe, it, expect } from "vitest";

import { buildCron, formatCronHuman, parseCron } from "./cronWizard";

describe("buildCron", () => {
  it("hourly at minute 15 → '15 * * * *'", () => {
    expect(buildCron("hourly", 15)).toBe("15 * * * *");
  });
  it("daily at hour 3 → '0 3 * * *'", () => {
    expect(buildCron("daily", 3)).toBe("0 3 * * *");
  });
});

describe("parseCron", () => {
  it("'15 * * * *' → hourly at minute 15", () => {
    expect(parseCron("15 * * * *")).toEqual({ recurrence: "hourly", offset: 15 });
  });
  it("'0 3 * * *' → daily at hour 3", () => {
    expect(parseCron("0 3 * * *")).toEqual({ recurrence: "daily", offset: 3 });
  });
  it("'0 0 * * *' → daily at hour 0 (midnight)", () => {
    expect(parseCron("0 0 * * *")).toEqual({ recurrence: "daily", offset: 0 });
  });
  it("'*/15 * * * *' → null (cron complexe)", () => {
    expect(parseCron("*/15 * * * *")).toBeNull();
  });
  it("'0 3 * * 1' → null (jour de semaine spécifié)", () => {
    expect(parseCron("0 3 * * 1")).toBeNull();
  });
  it("'invalid' → null", () => {
    expect(parseCron("invalid")).toBeNull();
  });
});

describe("formatCronHuman", () => {
  it("'15 * * * *' → 'Toutes les heures à xx:15'", () => {
    expect(formatCronHuman("15 * * * *")).toBe("Toutes les heures à xx:15");
  });
  it("'0 3 * * *' → 'Tous les jours à 03:00'", () => {
    expect(formatCronHuman("0 3 * * *")).toBe("Tous les jours à 03:00");
  });
  it("cron complexe → renvoie le cron brut", () => {
    expect(formatCronHuman("*/15 * * * *")).toBe("*/15 * * * *");
  });
});
