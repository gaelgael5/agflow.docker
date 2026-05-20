export type RecurrenceType =
  | "hourly"
  | "daily"
  | "weekly"
  | "interval-minutes"
  | "interval-hours";

export interface CronParts {
  recurrence: RecurrenceType;
  hour: number; // 0-23, ignoré pour hourly/interval-*
  minute: number; // 0-59
  dayOfWeek: number; // 0-6, 0=dimanche ; ignoré sauf pour weekly
  intervalN: number; // 1-59 (interval-minutes) ou 1-23 (interval-hours)
}

const DAYS_FR = [
  "dimanche",
  "lundi",
  "mardi",
  "mercredi",
  "jeudi",
  "vendredi",
  "samedi",
];

export function buildCron(parts: CronParts): string {
  if (parts.recurrence === "interval-minutes") {
    return `*/${parts.intervalN} * * * *`;
  }
  if (parts.recurrence === "interval-hours") {
    return `0 */${parts.intervalN} * * *`;
  }
  if (parts.recurrence === "hourly") {
    return `${parts.minute} * * * *`;
  }
  if (parts.recurrence === "weekly") {
    return `${parts.minute} ${parts.hour} * * ${parts.dayOfWeek}`;
  }
  return `${parts.minute} ${parts.hour} * * *`;
}

export function parseCron(cron: string | null | undefined): CronParts | null {
  if (!cron || typeof cron !== "string") return null;
  const tokens = cron.trim().split(/\s+/);
  if (tokens.length !== 5) return null;
  const min = tokens[0] ?? "";
  const hr = tokens[1] ?? "";
  const dom = tokens[2] ?? "";
  const mon = tokens[3] ?? "";
  const dow = tokens[4] ?? "";

  if (dom !== "*" || mon !== "*") return null;

  // Pattern interval-minutes : "*/N * * * *"
  const minIntervalMatch = /^\*\/(\d+)$/.exec(min);
  if (minIntervalMatch && hr === "*" && dow === "*") {
    const intervalN = parseInt(minIntervalMatch[1] ?? "0", 10);
    if (intervalN >= 1 && intervalN <= 59) {
      return {
        recurrence: "interval-minutes",
        hour: 0,
        minute: 0,
        dayOfWeek: 0,
        intervalN,
      };
    }
    return null;
  }

  // Pattern interval-hours : "0 */N * * *"
  const hrIntervalMatch = /^\*\/(\d+)$/.exec(hr);
  if (hrIntervalMatch && min === "0" && dow === "*") {
    const intervalN = parseInt(hrIntervalMatch[1] ?? "0", 10);
    if (intervalN >= 1 && intervalN <= 23) {
      return {
        recurrence: "interval-hours",
        hour: 0,
        minute: 0,
        dayOfWeek: 0,
        intervalN,
      };
    }
    return null;
  }

  if (!/^\d+$/.test(min)) return null;
  const minute = parseInt(min, 10);
  if (minute < 0 || minute > 59) return null;

  if (hr === "*") {
    if (dow !== "*") return null;
    return {
      recurrence: "hourly",
      hour: 0,
      minute,
      dayOfWeek: 0,
      intervalN: 0,
    };
  }

  if (!/^\d+$/.test(hr)) return null;
  const hour = parseInt(hr, 10);
  if (hour < 0 || hour > 23) return null;

  if (dow === "*") {
    return {
      recurrence: "daily",
      hour,
      minute,
      dayOfWeek: 0,
      intervalN: 0,
    };
  }

  if (/^\d+$/.test(dow)) {
    const dayOfWeek = parseInt(dow, 10);
    if (dayOfWeek < 0 || dayOfWeek > 6) return null;
    return {
      recurrence: "weekly",
      hour,
      minute,
      dayOfWeek,
      intervalN: 0,
    };
  }

  return null;
}

export function formatCronHuman(cron: string | null | undefined): string {
  const parsed = parseCron(cron);
  if (parsed === null) return cron ?? "";

  if (parsed.recurrence === "interval-minutes") {
    return `Toutes les ${parsed.intervalN} minutes`;
  }
  if (parsed.recurrence === "interval-hours") {
    return `Toutes les ${parsed.intervalN} heures`;
  }
  const mm = String(parsed.minute).padStart(2, "0");
  if (parsed.recurrence === "hourly") {
    return `Toutes les heures à xx:${mm}`;
  }
  const hh = String(parsed.hour).padStart(2, "0");
  if (parsed.recurrence === "weekly") {
    const day = DAYS_FR[parsed.dayOfWeek] ?? `jour ${parsed.dayOfWeek}`;
    return `Tous les ${day}s à ${hh}:${mm}`;
  }
  return `Tous les jours à ${hh}:${mm}`;
}
