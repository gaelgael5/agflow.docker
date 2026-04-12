import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy } from "lucide-react";
import { useBuild } from "@/hooks/useBuild";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface Props {
  dockerfileId: string;
  dockerfileName: string;
  buildId: string;
  onClose: () => void;
}

const ERROR_PATTERN =
  /\b(error|erreur|failed|failure|fatal|exception|cannot|not found|denied|refused)\b/i;

interface Segment {
  key: string;
  text: string;
  isError: boolean;
}

function segmentLogs(logs: string): Segment[] {
  return logs.split("\n").map((line, idx) => ({
    key: `${idx}-${line.length}`,
    text: line,
    isError: ERROR_PATTERN.test(line),
  }));
}

export function BuildModal({
  dockerfileId,
  dockerfileName,
  buildId,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const build = useBuild(dockerfileId, buildId);
  const logsRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  const segments = useMemo(
    () => segmentLogs(build?.logs ?? ""),
    [build?.logs],
  );

  useEffect(() => {
    const el = logsRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [build?.logs]);

  async function handleCopy() {
    if (!build?.logs) return;
    try {
      await navigator.clipboard.writeText(build.logs);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      return;
    } catch {
      // Clipboard API unavailable (insecure context, permissions); fall back below.
    }
    const textarea = document.createElement("textarea");
    textarea.value = build.logs;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } finally {
      document.body.removeChild(textarea);
    }
  }

  const statusVariant = (() => {
    if (!build) return "secondary" as const;
    if (build.status === "success") return "success" as const;
    if (build.status === "failed") return "destructive" as const;
    return "secondary" as const;
  })();

  const statusLabel = (() => {
    if (!build) return "…";
    if (build.status === "success") return t("dockerfiles.build_modal.success");
    if (build.status === "failed") return t("dockerfiles.build_modal.failed");
    return t("dockerfiles.build_modal.running");
  })();

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>
            {t("dockerfiles.build_modal.title", { dockerfile: dockerfileName })}
          </DialogTitle>
          {build ? (
            <DialogDescription className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant}>{statusLabel}</Badge>
              <code className="font-mono text-[11px]">{build.image_tag}</code>
            </DialogDescription>
          ) : (
            <DialogDescription className="sr-only">
              {t("dockerfiles.build_modal.running")}
            </DialogDescription>
          )}
        </DialogHeader>

        {build && (
          <>
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                {t("dockerfiles.build_modal.logs")}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={handleCopy}
                disabled={!build.logs}
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    {t("dockerfiles.build_modal.copied")}
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    {t("dockerfiles.build_modal.copy")}
                  </>
                )}
              </Button>
            </div>
            <pre
              ref={logsRef}
              className="flex-1 overflow-auto bg-zinc-900 text-zinc-100 rounded-md p-3 text-[11px] font-mono whitespace-pre-wrap min-h-[200px]"
            >
              {build.logs ? (
                segments.map((seg) => (
                  <div
                    key={seg.key}
                    className={cn(seg.isError && "text-red-400")}
                  >
                    {seg.text || "\u00a0"}
                  </div>
                ))
              ) : (
                <span className="text-zinc-500">…</span>
              )}
            </pre>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("dockerfiles.build_modal.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
