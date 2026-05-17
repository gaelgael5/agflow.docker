import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props = {
  selected: string[];
  available: string[];
  onChange: (next: string[]) => void;
};

export function GitSyncTablesPicker({ selected, available, onChange }: Props) {
  const { t } = useTranslation();
  const [tableToAdd, setTableToAdd] = useState<string>("");

  const availableToAdd = available.filter((tb) => !selected.includes(tb));

  const handleAdd = (table: string) => {
    if (!table || selected.includes(table)) return;
    onChange([...selected, table]);
    setTableToAdd("");
  };

  const handleRemove = (table: string) => {
    onChange(selected.filter((tb) => tb !== table));
  };

  return (
    <div className="space-y-1">
      <Label>{t("settings.gitSync.config.selectedTables")}</Label>
      <Select
        value={tableToAdd}
        onValueChange={handleAdd}
        disabled={availableToAdd.length === 0}
      >
        <SelectTrigger>
          <SelectValue
            placeholder={t("settings.gitSync.config.selectedTablesPlaceholder")}
          />
        </SelectTrigger>
        <SelectContent>
          {availableToAdd.map((tb) => (
            <SelectItem key={tb} value={tb}>
              {tb}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="flex flex-wrap gap-1 pt-2 min-h-[24px]">
        {selected.length === 0 ? (
          <p className="text-[12px] text-muted-foreground">
            {t("settings.gitSync.config.selectedTablesEmpty")}
          </p>
        ) : (
          selected.map((tb) => (
            <Badge
              key={tb}
              variant="secondary"
              className="cursor-pointer"
              onClick={() => handleRemove(tb)}
            >
              {tb} ×
            </Badge>
          ))
        )}
      </div>
    </div>
  );
}
