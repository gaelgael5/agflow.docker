import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { VaultSecretItem } from "@/lib/restoreApi";

interface VaultSecretPickerProps {
  label: string;
  secrets: VaultSecretItem[];
  value: string;
  onChange: (value: string) => void;
  optional?: boolean;
}

export function VaultSecretPicker({
  label,
  secrets,
  value,
  onChange,
  optional = false,
}: VaultSecretPickerProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="space-y-1">
      <Label>{label}{optional && <span className="ml-1 text-muted-foreground text-xs">({t("common.optional")})</span>}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger>
          <SelectValue placeholder={t("restore.picker_placeholder")} />
        </SelectTrigger>
        <SelectContent>
          {optional && (
            <SelectItem value="">{t("restore.picker_none")}</SelectItem>
          )}
          {secrets.map((s) => (
            <SelectItem key={s.name} value={s.name}>
              <span className="font-mono text-sm">{s.name}</span>
              {s.tags.length > 0 && (
                <span className="ml-2 text-muted-foreground text-xs">
                  [{s.tags.join(", ")}]
                </span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
