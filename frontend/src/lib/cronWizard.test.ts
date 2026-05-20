import { describe, it, expect } from "vitest";

import { buildCron, formatCronHuman, parseCron } from "./cronWizard";

describe("buildCron", () => {
  it("hourly at minute 15 → '15 * * * *'", () => {
    expect(
      buildCron({ recurrence: "hourly", hour: 0, minute: 15, dayOfWeek: 0 }),
    ).toBe("15 * * * *");
  });
  it("daily at 03:00 → '0 3 * * *'", () => {
    expect(
      buildCron({ recurrence: "daily", hour: 3, minute: 0, dayOfWeek: 0 }),
    ).toBe("0 3 * * *");
  });
  it("daily at 14:30 → '30 14 * * *'", () => {
    expect(
      buildCron({ recurrence: "daily", hour: 14, minute: 30, dayOfWeek: 0 }),
    ).toBe("30 14 * * *");
  });
  it("weekly Sunday 02:00 → '0 2 * * 0'", () => {
    expect(
      buildCron({ recurrence: "weekly", hour: 2, minute: 0, dayOfWeek: 0 }),
    ).toBe("0 2 * * 0");
  });
  it("weekly Wednesday 14:30 → '30 14 * * 3'", () => {
    expect(
      buildCron({ recurrence: "weekly", hour: 14, minute: 30, dayOfWeek: 3 }),
    ).toBe("30 14 * * 3");
  });
});

describe("parseCron", () => {
  it("'15 * * * *' → hourly minute 15", () => {
    expect(parseCron("15 * * * *")).toEqual({
      recurrence: "hourly",
      hour: 0,
      minute: 15,
      dayOfWeek: 0,
    });
  });
  it("'0 3 * * *' → daily 03:00", () => {
    expect(parseCron("0 3 * * *")).toEqual({
      recurrence: "daily",
      hour: 3,
      minute: 0,
      dayOfWeek: 0,
    });
  });
  it("'30 14 * * *' → daily 14:30", () => {
    expect(parseCron("30 14 * * *")).toEqual({
      recurrence: "daily",
      hour: 14,
      minute: 30,
      dayOfWeek: 0,
    });
  });
  it("'0 0 * * *' → daily 00:00 (midnight)", () => {
    expect(parseCron("0 0 * * *")).toEqual({
      recurrence: "daily",
      hour: 0,
      minute: 0,
      dayOfWeek: 0,
    });
  });
  it("'0 2 * * 0' → weekly Sunday 02:00", () => {
    expect(parseCron("0 2 * * 0")).toEqual({
      recurrence: "weekly",
      hour: 2,
      minute: 0,
      dayOfWeek: 0,
    });
  });
  it("'30 14 * * 3' → weekly Wednesday 14:30", () => {
    expect(parseCron("30 14 * * 3")).toEqual({
      recurrence: "weekly",
      hour: 14,
      minute: 30,
      dayOfWeek: 3,
    });
  });
  it("'*/15 * * * *' → null (cron complexe)", () => {
    expect(parseCron("*/15 * * * *")).toBeNull();
  });
  it("'15 * * * 1' → null (hourly avec jour de semaine)", () => {
    expect(parseCron("15 * * * 1")).toBeNull();
  });
  it("'0 2 * * 7' → null (dayOfWeek hors 0-6)", () => {
    expect(parseCron("0 2 * * 7")).toBeNull();
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
  it("'30 14 * * *' → 'Tous les jours à 14:30'", () => {
    expect(formatCronHuman("30 14 * * *")).toBe("Tous les jours à 14:30");
  });
  it("'0 2 * * 0' → 'Tous les dimanches à 02:00'", () => {
    expect(formatCronHuman("0 2 * * 0")).toBe("Tous les dimanches à 02:00");
  });
  it("'30 14 * * 3' → 'Tous les mercredis à 14:30'", () => {
    expect(formatCronHuman("30 14 * * 3")).toBe("Tous les mercredis à 14:30");
  });
  it("cron complexe → renvoie le cron brut", () => {
    expect(formatCronHuman("*/15 * * * *")).toBe("*/15 * * * *");
  });
});
