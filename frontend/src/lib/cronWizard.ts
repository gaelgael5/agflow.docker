export type RecurrenceType = "hourly" | "daily";

export interface CronParts {
  recurrence: RecurrenceType;
  hour: number; // 0-23, ignoré pour hourly (toujours 0)
  minute: number; // 0-59
}

export function buildCron(parts: CronParts): string {
  if (parts.recurrence === "hourly") {
    return `${parts.minute} * * * *`;
  }
  return `${parts.minute} ${parts.hour} * * *`;
}

export function parseCron(cron: string): CronParts | null {
  const tokens = cron.trim().split(/\s+/);
  if (tokens.length !== 5) return null;
  const min = tokens[0] ?? "";
  const hr = tokens[1] ?? "";
  const dom = tokens[2] ?? "";
  const mon = tokens[3] ?? "";
  const dow = tokens[4] ?? "";

  if (dom !== "*" || mon !== "*" || dow !== "*") return null;
  if (!/^\d+$/.test(min)) return null;
  const minute = parseInt(min, 10);
  if (minute < 0 || minute > 59) return null;

  if (hr === "*") {
    return { recurrence: "hourly", hour: 0, minute };
  }

  if (/^\d+$/.test(hr)) {
    const hour = parseInt(hr, 10);
    if (hour < 0 || hour > 23) return null;
    return { recurrence: "daily", hour, minute };
  }

  return null;
}

export function formatCronHuman(cron: string): string {
  const parsed = parseCron(cron);
  if (parsed === null) return cron;

  const mm = String(parsed.minute).padStart(2, "0");
  if (parsed.recurrence === "hourly") {
    return `Toutes les heures à xx:${mm}`;
  }
  const hh = String(parsed.hour).padStart(2, "0");
  return `Tous les jours à ${hh}:${mm}`;
}
