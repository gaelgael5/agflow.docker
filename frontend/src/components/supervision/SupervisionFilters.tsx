import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface Filters {
  status: "all" | "idle" | "busy" | "error";
  search: string;
  includeDestroyed: boolean;
}

interface Props {
  value: Filters;
  onChange: (next: Filters) => void;
}

export function SupervisionFilters({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Select
        value={value.status}
        onValueChange={(s) =>
          onChange({ ...value, status: s as Filters["status"] })
        }
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder={t("supervision.filters.status.label")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("supervision.filters.status.all")}</SelectItem>
          <SelectItem value="idle">{t("supervision.filters.status.idle")}</SelectItem>
          <SelectItem value="busy">{t("supervision.filters.status.busy")}</SelectItem>
          <SelectItem value="error">{t("supervision.filters.status.error")}</SelectItem>
        </SelectContent>
      </Select>

      <Input
        type="search"
        placeholder={t("supervision.filters.search_placeholder")}
        value={value.search}
        onChange={(e) => onChange({ ...value, search: e.target.value })}
        className="max-w-xs"
      />

      <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
        <input
          type="checkbox"
          checked={value.includeDestroyed}
          onChange={(e) =>
            onChange({ ...value, includeDestroyed: e.target.checked })
          }
          className="h-4 w-4 rounded border-input"
        />
        {t("supervision.filters.include_destroyed")}
      </label>
    </div>
  );
}
