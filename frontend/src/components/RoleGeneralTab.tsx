import { useTranslation } from "react-i18next";
import type { LLMType, RoleSummary } from "@/lib/rolesApi";

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
    <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: "1rem" }}>
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
      <div style={{ display: "flex", gap: "1rem" }}>
        <label>
          <strong>{t("roles.general.llm_type")}</strong>
          <select
            value={role.llm_type}
            onChange={(e) => onChange({ llm_type: e.target.value as LLMType })}
            style={{ display: "block" }}
          >
            <option value="single">{t("roles.general.llm_single")}</option>
            <option value="multi">{t("roles.general.llm_multi")}</option>
          </select>
        </label>
        <label>
          <strong>{t("roles.general.temperature")}</strong>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={role.temperature}
            onChange={(e) => onChange({ temperature: parseFloat(e.target.value) })}
            style={{ display: "block", width: "100px" }}
          />
        </label>
        <label>
          <strong>{t("roles.general.max_tokens")}</strong>
          <input
            type="number"
            step="256"
            min="1"
            value={role.max_tokens}
            onChange={(e) => onChange({ max_tokens: parseInt(e.target.value, 10) })}
            style={{ display: "block", width: "120px" }}
          />
        </label>
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
