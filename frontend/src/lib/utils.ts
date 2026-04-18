import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// Shared z-index counter for floating windows (logs, chat, terminal).
// Calling bringToFront() returns the next highest value so the caller
// can assign it to their own z-index state and appear above all others.
let _floatingZIndex = 50;
export function bringToFront(): number {
  _floatingZIndex += 1;
  return _floatingZIndex;
}

const _SECRET_KEY_RE = /(_API_KEY|_SECRET|_TOKEN|_PASSWORD|_PASS|_KEY|^APIKEY$|^API_KEY$)/i;
const _SECRET_VAL_RE = /^[a-z0-9_-]{20,}$/i;

/** Mask secret values in .env content for display only. */
export function maskEnvSecrets(content: string): string {
  return content.replace(
    /^([A-Za-z_]\w*)=(.+)$/gm,
    (_match, key: string, val: string) =>
      _SECRET_KEY_RE.test(key) || _SECRET_VAL_RE.test(val.trim())
        ? `${key}=${"*".repeat(Math.min(val.length, 20))}`
        : `${key}=${val}`,
  );
}
