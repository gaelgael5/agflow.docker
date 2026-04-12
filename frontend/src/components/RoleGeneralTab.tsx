import { useTranslation } from "react-i18next";
import type { RoleSummary } from "@/lib/rolesApi";
import { useServiceTypes } from "@/hooks/useServiceTypes";
import { MarkdownEditor } from "./MarkdownEditor";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  role: RoleSummary;
  onChange: (updates: Partial<RoleSummary>) => void;
}

export function RoleGeneralTab({ role, onChange }: Props) {
  const { t } = useTranslation();
  const { serviceTypes } = useServiceTypes();

  function toggleService(service: string) {
    const current = role.service_types ?? [];
    const next = current.includes(service)
      ? current.filter((s) => s !== service)
      : [...current, service];
    onChange({ service_types: next });
  }

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card>
        <CardContent className="pt-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>{t("roles.general.id")}</Label>
              <Input value={role.id} disabled className="font-mono text-[12px]" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t("roles.general.display_name")}</Label>
              <Input
                value={role.display_name}
                onChange={(e) => onChange({ display_name: e.target.value })}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("roles.general.description")}</Label>
            <Textarea
              value={role.description}
              onChange={(e) => onChange({ description: e.target.value })}
              rows={3}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="flex-1 flex flex-col min-h-0">
        <CardContent className="pt-5 flex-1 flex flex-col min-h-0">
          <Label className="mb-2 block shrink-0">
            {t("roles.identity.label")}
          </Label>
          <MarkdownEditor
            value={role.identity_md}
            onChange={(v) => onChange({ identity_md: v })}
            placeholder={t("roles.identity.placeholder")}
            minHeight={400}
            fill
          />
        </CardContent>
      </Card>

      <Card className="shrink-0">
        <CardContent className="pt-5">
          <Label className="mb-3 block">
            {t("roles.general.service_types")}
          </Label>
          <div className="flex flex-wrap gap-3">
            {(serviceTypes ?? []).map((st) => (
              <label
                key={st.name}
                className="flex items-center gap-2 text-[13px] cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={role.service_types.includes(st.name)}
                  onChange={() => toggleService(st.name)}
                  className="accent-primary"
                />
                {st.display_name}
              </label>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
