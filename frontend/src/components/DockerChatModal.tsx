import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import { slugify } from "@/lib/slugify";

interface GeneratedDockerfile {
  dockerfile: string;
  entrypoint_sh: string;
  run_cmd_md: string;
  reasoning: string;
}

interface Props {
  onClose: () => void;
  onAccept: (
    dockerfileId: string,
    displayName: string,
    files: GeneratedDockerfile,
  ) => Promise<void>;
}

export function DockerChatModal({ onClose, onAccept }: Props) {
  const { t } = useTranslation();
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [result, setResult] = useState<GeneratedDockerfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    "dockerfile" | "entrypoint_sh" | "run_cmd_md"
  >("dockerfile");
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<GeneratedDockerfile>(
        "/admin/dockerfiles/chat-generate",
        { description },
      );
      setResult(res.data);
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status;
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      if (status === 412) {
        setError(t("dockerfiles.chat.error_no_key"));
      } else if (status === 502) {
        setError(t("dockerfiles.chat.error_llm", { detail: detail ?? "" }));
      } else {
        setError(detail ?? t("dockerfiles.chat.error_generic"));
      }
    } finally {
      setGenerating(false);
    }
  }

  async function handleAccept() {
    if (!result || !displayName || !slug) return;
    setAccepting(true);
    try {
      await onAccept(slug, displayName, result);
      onClose();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(detail ?? t("dockerfiles.chat.error_generic"));
    } finally {
      setAccepting(false);
    }
  }

  function updateDisplayName(v: string) {
    setDisplayName(v);
    if (!slugTouched) setSlug(slugify(v));
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        padding: "2rem",
        overflowY: "auto",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          padding: "1.5rem",
          maxWidth: 900,
          width: "100%",
          maxHeight: "90vh",
          overflowY: "auto",
          borderRadius: "8px",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
          }}
        >
          <div>
            <h2 style={{ margin: 0 }}>{t("dockerfiles.chat.title")}</h2>
            <p style={{ color: "#666", fontSize: "13px", margin: "0.25rem 0" }}>
              {t("dockerfiles.chat.subtitle")}
            </p>
          </div>
          <button type="button" onClick={onClose}>
            ×
          </button>
        </div>

        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t("dockerfiles.chat.placeholder")}
          rows={4}
          disabled={generating}
          style={{
            width: "100%",
            marginTop: "1rem",
            padding: "0.5rem",
            fontFamily: "inherit",
            fontSize: "13px",
            border: "1px solid #ccc",
            borderRadius: "4px",
          }}
        />

        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginTop: "0.5rem",
          }}
        >
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating || description.trim().length < 10}
          >
            {generating
              ? t("dockerfiles.chat.generating")
              : t("dockerfiles.chat.generate_button")}
          </button>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              marginTop: "0.5rem",
              padding: "0.5rem",
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              color: "#991b1b",
              fontSize: "12px",
              borderRadius: "4px",
            }}
          >
            {error}
          </div>
        )}

        {result && (
          <div style={{ marginTop: "1.5rem" }}>
            {result.reasoning && (
              <div
                style={{
                  padding: "0.5rem 0.75rem",
                  background: "#eff6ff",
                  border: "1px solid #bfdbfe",
                  borderRadius: "4px",
                  fontSize: "12px",
                  color: "#1e3a8a",
                  marginBottom: "0.75rem",
                }}
              >
                <strong>
                  {t("dockerfiles.chat.reasoning")}:
                </strong>{" "}
                {result.reasoning}
              </div>
            )}

            <div
              style={{ display: "flex", gap: "0.25rem", marginBottom: "0.5rem" }}
            >
              {(["dockerfile", "entrypoint_sh", "run_cmd_md"] as const).map(
                (tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveTab(tab)}
                    style={{
                      padding: "4px 10px",
                      fontSize: "12px",
                      fontFamily: "monospace",
                      background: activeTab === tab ? "#e0e7ff" : "transparent",
                      border: "1px solid #ccc",
                      borderRadius: "3px",
                      cursor: "pointer",
                    }}
                  >
                    {tab === "dockerfile"
                      ? "Dockerfile"
                      : tab === "entrypoint_sh"
                        ? "entrypoint.sh"
                        : "run.cmd.md"}
                  </button>
                ),
              )}
            </div>

            <pre
              style={{
                background: "#1e293b",
                color: "#e2e8f0",
                padding: "0.75rem",
                fontSize: "11px",
                fontFamily: "ui-monospace, SFMono-Regular, monospace",
                maxHeight: "300px",
                overflow: "auto",
                borderRadius: "4px",
                whiteSpace: "pre-wrap",
                margin: 0,
              }}
            >
              {result[activeTab]}
            </pre>

            <div
              style={{
                marginTop: "1rem",
                padding: "0.75rem",
                border: "1px solid #e5e7eb",
                borderRadius: "4px",
                background: "#f9fafb",
              }}
            >
              <strong style={{ fontSize: "13px" }}>
                {t("dockerfiles.chat.accept_header")}
              </strong>
              <div
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  marginTop: "0.5rem",
                  alignItems: "center",
                }}
              >
                <input
                  type="text"
                  placeholder={t("dockerfiles.new_dockerfile_name_prompt")}
                  value={displayName}
                  onChange={(e) => updateDisplayName(e.target.value)}
                  style={{ flex: 1, padding: "4px 8px", fontSize: "13px" }}
                />
                <input
                  type="text"
                  placeholder={t("dockerfiles.new_dockerfile_id_prompt")}
                  value={slug}
                  onChange={(e) => {
                    setSlugTouched(true);
                    setSlug(e.target.value);
                  }}
                  style={{
                    width: 160,
                    padding: "4px 8px",
                    fontSize: "12px",
                    fontFamily: "monospace",
                  }}
                />
                <button
                  type="button"
                  onClick={handleAccept}
                  disabled={
                    accepting || !displayName.trim() || !slug.trim()
                  }
                >
                  {accepting
                    ? t("dockerfiles.chat.creating")
                    : t("dockerfiles.chat.accept_button")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
