import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export interface LogsWindowProps {
  containerId: string;
  containerName: string;
  onClose: () => void;
}

const STORAGE_KEY = "agflow.logs.position";

export function LogsWindow({
  containerId,
  containerName,
  onClose,
}: LogsWindowProps) {
  const logsRef = useRef<HTMLPreElement>(null);
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [position, setPosition] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved) as { x: number; y: number };
    } catch { /* ignore */ }
    return { x: 120, y: 120 };
  });
  const [size, setSize] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY + ".size");
      if (saved) return JSON.parse(saved) as { w: number; h: number };
    } catch { /* ignore */ }
    return { w: 700, h: 400 };
  });

  const dragOffsetRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  } | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
      localStorage.setItem(STORAGE_KEY + ".size", JSON.stringify(size));
    } catch { /* ignore */ }
  }, [position, size]);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await api.get<string>(
        `/admin/containers/${containerId}/logs`,
        { params: { tail: 500 } },
      );
      setLogs(typeof res.data === "string" ? res.data : JSON.stringify(res.data));
      setLoading(false);
    } catch {
      setLogs("Error fetching logs");
      setLoading(false);
    }
  }, [containerId]);

  useEffect(() => {
    fetchLogs();
    pollRef.current = setInterval(fetchLogs, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchLogs]);

  useEffect(() => {
    const el = logsRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  function onHeaderMouseDown(e: ReactMouseEvent<HTMLDivElement>) {
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
      const off = dragOffsetRef.current;
      if (off) {
        setPosition({
          x: Math.max(0, Math.min(window.innerWidth - 320, e.clientX - off.dx)),
          y: Math.max(0, Math.min(window.innerHeight - 120, e.clientY - off.dy)),
        });
      }
      const rs = resizeRef.current;
      if (rs) {
        setSize({
          w: Math.max(400, Math.min(window.innerWidth - 40, rs.startW + (e.clientX - rs.startX))),
          h: Math.max(200, Math.min(window.innerHeight - 40, rs.startH + (e.clientY - rs.startY))),
        });
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

  return (
    <div
      className="fixed z-50 flex flex-col rounded-lg border bg-background shadow-2xl overflow-hidden"
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${size.w}px`,
        height: `${size.h}px`,
      }}
    >
      <div
        className="flex items-center justify-between px-3 py-1.5 bg-muted/60 border-b cursor-move select-none shrink-0"
        onMouseDown={onHeaderMouseDown}
      >
        <span className="text-xs font-mono text-muted-foreground truncate">
          Logs — {containerName}
        </span>
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 shrink-0"
          onClick={onClose}
        >
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>

      <pre
        ref={logsRef}
        className="flex-1 min-h-0 overflow-auto p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap bg-muted text-foreground"
      >
        {loading ? "Loading..." : logs || "(no logs)"}
      </pre>

      <div
        className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
        onMouseDown={onResizeMouseDown}
      >
        <svg viewBox="0 0 16 16" className="w-full h-full text-muted-foreground/40">
          <path d="M14 14L14 8M14 14L8 14" stroke="currentColor" strokeWidth="1.5" fill="none" />
        </svg>
      </div>
    </div>
  );
}
