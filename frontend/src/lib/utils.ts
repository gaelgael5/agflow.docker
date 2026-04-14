import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const _SECRET_KEY_RE = /_(API_KEY|SECRET|TOKEN|PASSWORD|PASS|KEY)$/i;

/** Mask secret values in .env content for display only. */
export function maskEnvSecrets(content: string): string {
  return content.replace(
    /^([A-Za-z_]\w*)=(.+)$/gm,
    (_match, key: string, val: string) =>
      _SECRET_KEY_RE.test(key)
        ? `${key}=${"*".repeat(Math.min(val.length, 20))}`
        : `${key}=${val}`,
  );
}
