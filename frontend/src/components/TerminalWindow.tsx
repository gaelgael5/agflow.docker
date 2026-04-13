import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import "@xterm/xterm/css/xterm.css";

export interface TerminalWindowProps {
  containerId: string;
  containerName: string;
  onClose: () => void;
}

const STORAGE_KEY = "agflow.terminal.position";

export function TerminalWindow({
  containerId,
  containerName,
  onClose,
}: TerminalWindowProps) {
  const termRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const [position, setPosition] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved) as { x: number; y: number };
    } catch {
      /* ignore */
    }
    return { x: 80, y: 80 };
  });
  const [size, setSize] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY + ".size");
      if (saved) return JSON.parse(saved) as { w: number; h: number };
    } catch {
      /* ignore */
    }
    return { w: 720, h: 480 };
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
    } catch {
      /* ignore */
    }
  }, [position, size]);

  const initTerminal = useCallback(() => {
    if (!termRef.current || xtermRef.current) return;

    const isDark = document.documentElement.classList.contains("dark");
    const bg = isDark ? "hsl(240, 6%, 12%)" : "hsl(240, 5%, 96%)";
    const fg = isDark ? "hsl(0, 0%, 98%)" : "hsl(240, 10%, 10%)";

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      theme: {
        background: bg,
        foreground: fg,
        cursor: fg,
        selectionBackground: "rgba(128,128,128,0.3)",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(termRef.current);
    fit.fit();

    xtermRef.current = term;
    fitRef.current = fit;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/api/admin/containers/${containerId}/terminal`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      term.writeln(`\x1b[90mConnected to ${containerName}\x1b[0m`);
      term.writeln("");
    };

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data));
      } else {
        term.write(ev.data as string);
      }
    };

    ws.onclose = (ev) => {
      term.writeln("");
      term.writeln(
        `\x1b[90mDisconnected (code ${ev.code})\x1b[0m`,
      );
    };

    ws.onerror = () => {
      term.writeln("\x1b[31mWebSocket error\x1b[0m");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    term.focus();
  }, [containerId, containerName]);

  useEffect(() => {
    initTerminal();
    return () => {
      wsRef.current?.close();
      xtermRef.current?.dispose();
      xtermRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
    };
  }, [initTerminal]);

  useEffect(() => {
    const fit = fitRef.current;
    if (fit) {
      try {
        fit.fit();
      } catch {
        /* terminal may not be ready */
      }
    }
  }, [size]);

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
          h: Math.max(300, Math.min(window.innerHeight - 40, rs.startH + (e.clientY - rs.startY))),
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
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-1.5 bg-muted/60 border-b cursor-move select-none shrink-0"
        onMouseDown={onHeaderMouseDown}
      >
        <span className="text-xs font-mono text-muted-foreground truncate">
          Terminal — {containerName}
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

      {/* Terminal */}
      <div ref={termRef} className="flex-1 min-h-0" />

      {/* Resize handle */}
      <div
        className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
        onMouseDown={onResizeMouseDown}
      >
        <svg
          viewBox="0 0 16 16"
          className="w-full h-full text-muted-foreground/40"
        >
          <path d="M14 14L14 8M14 14L8 14" stroke="currentColor" strokeWidth="1.5" fill="none" />
        </svg>
      </div>
    </div>
  );
}
