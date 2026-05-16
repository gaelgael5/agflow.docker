import { adminBackupRemotesApi, type GDriveOAuthSessionInfo } from "./adminBackupRemotesApi";

export class PopupBlockedError extends Error {
  constructor() {
    super("Popup blocked by browser");
  }
}

export class OAuthAbortedError extends Error {
  constructor() {
    super("OAuth flow aborted by user");
  }
}

export class OAuthError extends Error {}

const POLL_INTERVAL_MS = 1500;
const TIMEOUT_MS = 5 * 60 * 1000;

export async function runGDriveOAuthFlow(params: {
  authorizeUrl: string;
  state: string;
}): Promise<GDriveOAuthSessionInfo> {
  const popup = window.open(params.authorizeUrl, "gdrive-oauth", "width=520,height=720");
  if (!popup) {
    throw new PopupBlockedError();
  }

  const start = Date.now();
  while (true) {
    if (Date.now() - start > TIMEOUT_MS) {
      try { popup.close(); } catch { /* ignore */ }
      throw new OAuthError("OAuth flow timed out");
    }
    if (popup.closed) {
      // Check une dernière fois si la session a été complétée juste avant la fermeture
      const info = await adminBackupRemotesApi.fetchGDriveOAuthSession(params.state);
      if (info.status === "completed") return info;
      throw new OAuthAbortedError();
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    try {
      const info = await adminBackupRemotesApi.fetchGDriveOAuthSession(params.state);
      if (info.status === "completed") {
        try { popup.close(); } catch { /* ignore */ }
        return info;
      }
      if (info.status === "failed") {
        try { popup.close(); } catch { /* ignore */ }
        throw new OAuthError("OAuth flow failed");
      }
    } catch (err) {
      // 404 sur la session = elle a expiré ou été purgée
      if ((err as { response?: { status?: number } }).response?.status === 404) {
        try { popup.close(); } catch { /* ignore */ }
        throw new OAuthError("OAuth session expired");
      }
      throw err;
    }
  }
}

export async function runGDriveReauthorize(connectionId: string): Promise<GDriveOAuthSessionInfo> {
  const { state, authorize_url } = await adminBackupRemotesApi.reauthorizeConnection(connectionId);
  return runGDriveOAuthFlow({ authorizeUrl: authorize_url, state });
}
