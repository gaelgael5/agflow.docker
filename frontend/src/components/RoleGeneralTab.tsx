import { useTranslation } from "react-i18next";
import type { RoleSummary } from "@/lib/rolesApi";
import { MarkdownEditor } from "./MarkdownEditor";

interface Props {
  role: RoleSummary;
  onChange: (updates: Partial<RoleSummary>) => void;
}

const SERVICE_TYPES = [
  "documentation",
  "code",
  "design",
  "automation",
  "task_list",
  "specs",
  "contract",
] as const;

export function RoleGeneralTab({ role, onChange }: Props) {
  const { t } = useTranslation();

  function toggleService(service: string) {
    const current = role.service_types ?? [];
    const next = current.includes(service)
      ? current.filter((s) => s !== service)
      : [...current, service];
    onChange({ service_types: next });
  }

  return (
    <div
      style={{
        maxWidth: 640,
        display: "flex",
        flexDirection: "column",
        gap: "1rem",
      }}
    >
      <div>
        <label>
          <strong>{t("roles.general.id")}</strong>
          <input
            type="text"
            value={role.id}
            disabled
            style={{ display: "block", width: "100%" }}
          />
        </label>
      </div>
      <div>
        <label>
          <strong>{t("roles.general.display_name")}</strong>
          <input
            type="text"
            value={role.display_name}
            onChange={(e) => onChange({ display_name: e.target.value })}
            style={{ display: "block", width: "100%" }}
          />
        </label>
      </div>
      <div>
        <label>
          <strong>{t("roles.general.description")}</strong>
          <textarea
            value={role.description}
            onChange={(e) => onChange({ description: e.target.value })}
            style={{ display: "block", width: "100%", minHeight: "80px" }}
          />
        </label>
      </div>
      <div>
        <strong>{t("roles.identity.label")}</strong>
        <MarkdownEditor
          value={role.identity_md}
          onChange={(v) => onChange({ identity_md: v })}
          placeholder={t("roles.identity.placeholder")}
          minHeight={240}
        />
      </div>
      <div>
        <strong>{t("roles.general.service_types")}</strong>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            marginTop: "0.5rem",
          }}
        >
          {SERVICE_TYPES.map((service) => (
            <label key={service} style={{ fontSize: "13px" }}>
              <input
                type="checkbox"
                checked={role.service_types.includes(service)}
                onChange={() => toggleService(service)}
              />{" "}
              {t(`roles.general.service_${service}`)}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
