export type RecurrenceType = "hourly" | "daily";

export function buildCron(recurrence: RecurrenceType, offset: number): string {
  if (recurrence === "hourly") return `${offset} * * * *`;
  return `0 ${offset} * * *`;
}

export function parseCron(
  cron: string,
): { recurrence: RecurrenceType; offset: number } | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const min = parts[0] ?? "";
  const hr = parts[1] ?? "";
  const dom = parts[2] ?? "";
  const mon = parts[3] ?? "";
  const dow = parts[4] ?? "";

  // "M * * * *" → hourly at minute M
  if (
    hr === "*" &&
    dom === "*" &&
    mon === "*" &&
    dow === "*" &&
    /^\d+$/.test(min)
  ) {
    const n = parseInt(min, 10);
    if (n >= 0 && n <= 59) return { recurrence: "hourly", offset: n };
  }

  // "0 H * * *" → daily at hour H
  if (
    min === "0" &&
    dom === "*" &&
    mon === "*" &&
    dow === "*" &&
    /^\d+$/.test(hr)
  ) {
    const n = parseInt(hr, 10);
    if (n >= 0 && n <= 23) return { recurrence: "daily", offset: n };
  }

  return null;
}

export function formatCronHuman(cron: string): string {
  const parsed = parseCron(cron);
  if (parsed === null) return cron; // fallback : afficher le cron brut

  if (parsed.recurrence === "hourly") {
    const mm = String(parsed.offset).padStart(2, "0");
    return `Toutes les heures à xx:${mm}`;
  }
  const hh = String(parsed.offset).padStart(2, "0");
  return `Tous les jours à ${hh}:00`;
}
