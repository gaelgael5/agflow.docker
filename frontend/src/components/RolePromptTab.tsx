import { useTranslation } from "react-i18next";
import { MarkdownEditor } from "./MarkdownEditor";
import type { RoleSummary } from "@/lib/rolesApi";

interface Props {
  role: RoleSummary;
  onRegenerate: () => void;
  regenerating: boolean;
  error: string | null;
}

export function RolePromptTab({
  role,
  onRegenerate,
  regenerating,
  error,
}: Props) {
  const { t } = useTranslation();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      <p
        style={{
          fontSize: "13px",
          color: "#555",
          background: "#f5f5f5",
          padding: "0.75rem",
          borderRadius: "4px",
          borderLeft: "3px solid #4f46e5",
          margin: 0,
        }}
      >
        {t("roles.prompt.explanation")}
      </p>
      <div>
        <button type="button" onClick={onRegenerate} disabled={regenerating}>
          {regenerating
            ? t("roles.prompt.generating")
            : t("roles.prompt.regenerate_button")}
        </button>
        {error && (
          <p role="alert" style={{ color: "red", marginTop: "0.5rem" }}>
            {error}
          </p>
        )}
      </div>
      <div>
        <h3>{t("roles.prompt.agent_title")}</h3>
        {role.prompt_agent_md ? (
          <MarkdownEditor
            value={role.prompt_agent_md}
            onChange={() => {}}
            readOnly
          />
        ) : (
          <p style={{ color: "#888", fontStyle: "italic" }}>
            {t("roles.prompt.empty")}
          </p>
        )}
      </div>
      <div>
        <h3>{t("roles.prompt.orchestrator_title")}</h3>
        {role.prompt_orchestrator_md ? (
          <MarkdownEditor
            value={role.prompt_orchestrator_md}
            onChange={() => {}}
            readOnly
          />
        ) : (
          <p style={{ color: "#888", fontStyle: "italic" }}>
            {t("roles.prompt.empty")}
          </p>
        )}
      </div>
    </div>
  );
}
