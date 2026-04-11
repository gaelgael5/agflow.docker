import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useBuild } from "@/hooks/useBuild";

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

  // Auto-scroll to the bottom whenever logs grow — mirrors a terminal feel.
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
    } catch {
      // Clipboard API may not be available (non-HTTPS); fall back to a prompt.
      window.prompt(t("dockerfiles.build_modal.copy_fallback"), build.logs);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "white",
          padding: "1.5rem",
          borderRadius: "8px",
          width: "min(900px, 90%)",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <h2 style={{ margin: 0 }}>
          {t("dockerfiles.build_modal.title", { dockerfile: dockerfileName })}
        </h2>
        {build && (
          <>
            <p style={{ fontSize: "13px", color: "#555" }}>
              <strong>{t("dockerfiles.build_modal.image_tag")}:</strong>{" "}
              <code>{build.image_tag}</code>
            </p>
            <p>
              <strong>Status:</strong>{" "}
              {build.status === "success"
                ? `✅ ${t("dockerfiles.build_modal.success")}`
                : build.status === "failed"
                  ? `❌ ${t("dockerfiles.build_modal.failed")}`
                  : `🔵 ${t("dockerfiles.build_modal.running")}`}
            </p>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <strong>{t("dockerfiles.build_modal.logs")}</strong>
              <button
                type="button"
                onClick={handleCopy}
                disabled={!build.logs}
                style={{
                  fontSize: "12px",
                  padding: "2px 8px",
                  cursor: build.logs ? "pointer" : "default",
                }}
              >
                {copied
                  ? t("dockerfiles.build_modal.copied")
                  : t("dockerfiles.build_modal.copy")}
              </button>
            </div>
            <pre
              ref={logsRef}
              style={{
                flex: 1,
                overflow: "auto",
                background: "#111",
                color: "#e5e7eb",
                padding: "0.75rem",
                fontSize: "12px",
                margin: "0.5rem 0",
                whiteSpace: "pre-wrap",
              }}
            >
              {build.logs
                ? segments.map((seg) => (
                    <div
                      key={seg.key}
                      style={{ color: seg.isError ? "#f87171" : undefined }}
                    >
                      {seg.text || "\u00a0"}
                    </div>
                  ))
                : "..."}
            </pre>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          style={{ alignSelf: "flex-end" }}
        >
          {t("dockerfiles.build_modal.close")}
        </button>
      </div>
    </div>
  );
}
