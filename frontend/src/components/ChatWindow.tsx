import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { bringToFront, cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useEmptyLaunchKeys } from "@/hooks/useEmptyLaunchKeys";

export interface ChatWindowProps {
  dockerfileId: string;
  agentSlug?: string;
  title?: string;
  onClose: () => void;
  secrets?: Record<string, string>;
  dockerfileJsonContent?: string | null;
}

interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system" | "error";
  text: string;
  streaming?: boolean;
}

interface TaskEvent {
  type?: string;
  task_id?: string;
  data?: unknown;
  message?: string;
  status?: string;
  exit_code?: number;
  role?: string;
  content?: string;
  kind?: string;
  payload?: Record<string, unknown>;
  tool_calls?: Array<Record<string, unknown>>;
}

const STORAGE_KEY_PREFIX = "agflow.chat.position.";

function randomId(): string {
  return Math.random().toString(36).slice(2, 11);
}

export function ChatWindow({
  dockerfileId,
  agentSlug,
  title,
  onClose,
  secrets,
  dockerfileJsonContent,
}: ChatWindowProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const { emptyKeys } = useEmptyLaunchKeys({
    dockerfileJsonContent,
    decryptedSecrets: secrets,
  });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [position, setPosition] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY_PREFIX + dockerfileId);
      if (saved) return JSON.parse(saved) as { x: number; y: number };
    } catch {
      /* ignore */
    }
    return { x: window.innerWidth - 520 - 24, y: window.innerHeight - 600 - 24 };
  });
  const [size, setSize] = useState(() => {
    try {
      const saved = localStorage.getItem(
        STORAGE_KEY_PREFIX + dockerfileId + ".size",
      );
      if (saved) return JSON.parse(saved) as { w: number; h: number };
    } catch {
      /* ignore */
    }
    return { w: 520, h: 600 };
  });
  const [zIndex, setZIndex] = useState(() => bringToFront());
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dragOffsetRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Persist last known position + size per dockerfile.
  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY_PREFIX + dockerfileId,
        JSON.stringify(position),
      );
      localStorage.setItem(
        STORAGE_KEY_PREFIX + dockerfileId + ".size",
        JSON.stringify(size),
      );
    } catch {
      /* ignore */
    }
  }, [position, size, dockerfileId]);

  // Auto-scroll to bottom when new messages arrive.
  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Focus textarea on mount.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Drag handling on the header.
  function onHeaderMouseDown(e: ReactMouseEvent<HTMLDivElement>) {
    // Don't trigger drag when clicking on the close button.
    if ((e.target as HTMLElement).closest("button")) return;
    dragOffsetRef.current = {
      dx: e.clientX - position.x,
      dy: e.clientY - position.y,
    };
    e.preventDefault();
  }

  function onResizeMouseDown(e: ReactMouseEvent<HTMLDivElement>) {
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startW: size.w,
      startH: size.h,
    };
    e.preventDefault();
    e.stopPropagation();
  }

  useEffect(() => {
    function onMove(e: MouseEvent) {
      // Drag (move window).
      const off = dragOffsetRef.current;
      if (off) {
        const nextX = Math.max(
          0,
          Math.min(window.innerWidth - 320, e.clientX - off.dx),
        );
        const nextY = Math.max(
          0,
          Math.min(window.innerHeight - 120, e.clientY - off.dy),
        );
        setPosition({ x: nextX, y: nextY });
      }
      // Resize.
      const rs = resizeRef.current;
      if (rs) {
        const nextW = Math.max(360, Math.min(window.innerWidth - 40, rs.startW + (e.clientX - rs.startX)));
        const nextH = Math.max(300, Math.min(window.innerHeight - 40, rs.startH + (e.clientY - rs.startY)));
        setSize({ w: nextW, h: nextH });
      }
    }
    function onUp() {
      dragOffsetRef.current = null;
      resizeRef.current = null;
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const appendMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateLastAgentMessage = useCallback(
    (updater: (text: string) => string) => {
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          const m = next[i]!;
          if (m.role === "agent" && m.streaming) {
            next[i] = { ...m, text: updater(m.text) };
            return next;
          }
        }
        return next;
      });
    },
    [],
  );

  const finalizeAgentMessage = useCallback(() => {
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }, []);

  async function handleSend() {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    appendMessage({ id: randomId(), role: "user", text });
    appendMessage({
      id: randomId(),
      role: "agent",
      text: "",
      streaming: true,
    });
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = localStorage.getItem("agflow_token");
      const taskUrl = agentSlug
        ? `/api/admin/agents/${agentSlug}/task`
        : `/api/admin/dockerfiles/${dockerfileId}/task`;
      const res = await fetch(
        taskUrl,
        {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            instruction: text,
            ...(secrets && Object.keys(secrets).length > 0
              ? { secrets }
              : {}),
          }),
        },
      );

      if (!res.ok || !res.body) {
        const errBody = await res.text();
        let message = errBody || res.statusText;
        try {
          const parsed = JSON.parse(errBody);
          if (typeof parsed.detail === "string") message = parsed.detail;
        } catch {
          /* plain text */
        }
        throw new Error(message);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, nl);
          buffer = buffer.slice(nl + 1);
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line) as TaskEvent;
            handleEvent(event);
          } catch {
            updateLastAgentMessage((t) => t + line + "\n");
          }
        }
      }
      if (buffer.trim()) {
        try {
          handleEvent(JSON.parse(buffer) as TaskEvent);
        } catch {
          updateLastAgentMessage((t) => t + buffer);
        }
      }
    } catch (err) {
      if ((err as { name?: string }).name !== "AbortError") {
        appendMessage({
          id: randomId(),
          role: "error",
          text: (err as Error).message || t("dockerfiles.chat_window.error"),
        });
      }
    } finally {
      finalizeAgentMessage();
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function handleEvent(event: TaskEvent) {
    if (event.role === "system" || event.role === "user") {
      return;
    }
    if (event.role === "assistant") {
      const content = event.content ?? "";
      const toolCalls = event.tool_calls ?? [];
      const toolTxt = toolCalls
        .map((tc) => {
          const fn = (tc.function ?? {}) as Record<string, unknown>;
          return `[tool:${fn.name ?? "?"}]`;
        })
        .join(" ");
      const full = [content, toolTxt].filter(Boolean).join(" ");
      if (full) updateLastAgentMessage((prev) => prev + full + "\n");
      return;
    }
    if (event.role === "tool") {
      const content = event.content ?? "";
      if (content) updateLastAgentMessage((prev) => prev + `[tool] ${content}\n`);
      return;
    }
    if (event.kind === "result" && event.payload) {
      const status = event.payload.status;
      const exitCode = event.payload.exit_code;
      if (status === "failure") {
        appendMessage({
          id: randomId(),
          role: "error",
          text: t("dockerfiles.chat_window.task_failed", {
            exit_code: String(exitCode ?? "?"),
          }),
        });
      }
      return;
    }
    if (event.kind === "event" && event.payload) {
      const text = (event.payload.text as string | undefined) ?? "";
      if (text) updateLastAgentMessage((prev) => prev + text + "\n");
      return;
    }
    if (event.type === "progress") {
      const snippet = renderEventData(event.data);
      if (snippet) updateLastAgentMessage((prev) => prev + snippet + "\n");
    } else if (event.type === "result") {
      const data =
        event.data && typeof event.data === "object"
          ? (event.data as Record<string, unknown>)
          : null;
      const status = data?.status;
      const exitCode = data?.exit_code;
      if (status === "failure") {
        appendMessage({
          id: randomId(),
          role: "error",
          text: t("dockerfiles.chat_window.task_failed", {
            exit_code: String(exitCode ?? "?"),
          }),
        });
      } else if (status === "success") {
        // no success banner — aider output speaks for itself
      } else {
        const snippet = renderEventData(event.data);
        if (snippet) updateLastAgentMessage((prev) => prev + snippet + "\n");
      }
    } else if (event.type === "done") {
      if (event.status === "failure") {
        appendMessage({
          id: randomId(),
          role: "error",
          text: t("dockerfiles.chat_window.container_exit_error", {
            exit_code: String(event.exit_code ?? "?"),
          }),
        });
      }
    } else if (event.type === "error") {
      appendMessage({
        id: randomId(),
        role: "error",
        text: event.message || "Error",
      });
    } else if (event.type === "raw") {
      updateLastAgentMessage((prev) => prev + String(event.data ?? "") + "\n");
    }
  }

  function renderEventData(data: unknown): string {
    if (data === undefined || data === null) return "";
    if (typeof data === "string") return data;
    try {
      return JSON.stringify(data);
    } catch {
      return String(data);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl+Enter (or Cmd+Enter on Mac) → send. Enter alone → newline.
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSend();
    }
  }

  function handleClose() {
    abortRef.current?.abort();
    onClose();
  }

  return (
    <div
      style={
        isMobile
          ? { position: "fixed", inset: 0, width: "100%", height: "100%", zIndex }
          : { position: "fixed", left: position.x, top: position.y, width: size.w, height: size.h, zIndex }
      }
      className={cn(
        "flex flex-col border border-border bg-card shadow-2xl overflow-hidden",
        !isMobile && "rounded-lg",
      )}
      onMouseDown={() => setZIndex(bringToFront())}
      role="dialog"
      aria-label={title ?? t("dockerfiles.chat_window.title", { id: dockerfileId })}
    >
      {/* Header (draggable on desktop) */}
      <div
        className={cn(
          "flex items-center justify-between px-4 py-2 bg-zinc-900 text-zinc-100 select-none border-b border-zinc-800",
          !isMobile && "cursor-move",
        )}
        onMouseDown={isMobile ? undefined : onHeaderMouseDown}
      >
        <div className="flex flex-col min-w-0">
          <span className="text-[12px] font-semibold truncate">
            {title ?? t("dockerfiles.chat_window.title", { id: dockerfileId })}
          </span>
          <span className="text-[10px] text-zinc-400">
            {streaming
              ? t("dockerfiles.chat_window.streaming")
              : t("dockerfiles.chat_window.idle")}
          </span>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={handleClose}
          className="h-6 w-6 text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800"
          aria-label={t("dockerfiles.chat_window.close")}
        >
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>

      {/* Empty launch keys banner */}
      {emptyKeys.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2 bg-yellow-50 dark:bg-yellow-950/40 border-b border-yellow-300 dark:border-yellow-900 text-yellow-900 dark:text-yellow-200 text-[12px]">
          <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>
            {t("chat.empty_launch_keys", { keys: emptyKeys.join(", ") })}
          </span>
        </div>
      )}

      {/* Messages */}
      <div
        ref={messagesRef}
        className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2 bg-background"
      >
        {messages.length === 0 ? (
          <p className="text-[12px] italic text-muted-foreground text-center mt-8">
            {t("dockerfiles.chat_window.empty")}
          </p>
        ) : (
          messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))
        )}
      </div>

      {/* Resize handle — bottom-right corner (desktop only) */}
      {!isMobile && <div
        onMouseDown={onResizeMouseDown}
        className="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize z-10"
        style={{
          background:
            "linear-gradient(135deg, transparent 50%, hsl(var(--border)) 50%)",
        }}
        aria-hidden
      />}

      {/* Input */}
      <div className="border-t p-2 bg-muted/30">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
          placeholder={t("dockerfiles.chat_window.placeholder")}
          rows={3}
          className="w-full resize-y min-h-[60px] max-h-[300px] rounded-md border border-input bg-background px-3 py-2 text-[13px] font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 focus-visible:border-ring disabled:opacity-50"
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-[10px] text-muted-foreground">
            {t("dockerfiles.chat_window.shortcut_hint")}
          </span>
          <Button
            type="button"
            size="sm"
            onClick={() => void handleSend()}
            disabled={streaming || !input.trim()}
          >
            <Send className="w-3.5 h-3.5" />
            {t("dockerfiles.chat_window.send")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  const isSystem = message.role === "system";
  return (
    <div
      className={cn(
        "flex",
        isUser ? "justify-end" : "justify-start",
        isSystem && "justify-center",
      )}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-lg px-3 py-2 text-[12px] whitespace-pre-wrap break-words",
          isUser && "bg-primary text-primary-foreground",
          message.role === "agent" && "bg-secondary text-foreground font-mono",
          isError &&
            "bg-destructive/10 text-destructive border border-destructive/30",
          isSystem &&
            "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-900/40 text-center text-[11px]",
          message.streaming && "opacity-80",
        )}
      >
        {message.text || (message.streaming ? "…" : "")}
      </div>
    </div>
  );
}
