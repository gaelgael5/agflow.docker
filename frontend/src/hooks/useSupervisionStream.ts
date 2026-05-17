import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type StreamStatus = "connecting" | "open" | "closed";

const BACKOFF_INITIAL_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const TOKEN_KEY = "agflow_token";

function buildUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${proto}://${host}/api/admin/supervision/stream?token=${encodeURIComponent(token)}`;
}

export function useSupervisionStream(): StreamStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let backoffMs = BACKOFF_INITIAL_MS;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      const token = localStorage.getItem(TOKEN_KEY) ?? "";
      socket = new WebSocket(buildUrl(token));

      socket.onopen = () => {
        if (cancelled) return;
        setStatus("open");
        backoffMs = BACKOFF_INITIAL_MS;
      };

      socket.onmessage = (event) => {
        if (cancelled) return;
        let ev: { type?: string; id?: string };
        try {
          ev = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!ev.type) return;

        if (ev.type.startsWith("instance.")) {
          queryClient.invalidateQueries({ queryKey: ["supervision", "overview"] });
          queryClient.invalidateQueries({ queryKey: ["supervision", "instances"] });
          if (ev.id) {
            queryClient.invalidateQueries({
              queryKey: ["supervision", "instance", ev.id],
            });
          }
        } else if (ev.type.startsWith("session.")) {
          queryClient.invalidateQueries({ queryKey: ["supervision", "overview"] });
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        reconnectTimer = setTimeout(() => {
          connect();
        }, backoffMs);
        backoffMs = Math.min(backoffMs * 2, BACKOFF_MAX_MS);
      };

      socket.onerror = () => {
        // onclose follows, handled there
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [queryClient]);

  return status;
}
