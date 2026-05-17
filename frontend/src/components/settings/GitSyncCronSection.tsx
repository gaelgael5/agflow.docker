import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const CRON_PRESETS: Record<string, string> = {
  hourly: "0 * * * *",
  daily4am: "0 4 * * *",
  weeklySun2am: "0 2 * * 0",
};

const PRESET_KEYS = ["hourly", "daily4am", "weeklySun2am"] as const;

type Props = {
  enabled: boolean;
  expr: string | null;
  onChangeEnabled: (enabled: boolean) => void;
  onChangeExpr: (expr: string | null) => void;
};

export function GitSyncCronSection({
  enabled,
  expr,
  onChangeEnabled,
  onChangeExpr,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <p className="text-[13px] font-medium">
        {t("settings.gitSync.config.cron")}
      </p>
      <label className="flex items-center gap-2 text-[13px]">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onChangeEnabled(e.target.checked)}
          className="h-4 w-4"
        />
        {t("settings.gitSync.config.cronEnabled")}
      </label>
      <div className="space-y-1">
        <Label htmlFor="cron_expr">
          {t("settings.gitSync.config.cronExpr")}
        </Label>
        <Input
          id="cron_expr"
          value={expr ?? ""}
          onChange={(e) => onChangeExpr(e.target.value || null)}
          placeholder="0 4 * * *"
          disabled={!enabled}
        />
        <div className="flex flex-wrap gap-1 pt-1">
          {PRESET_KEYS.map((preset) => (
            <Button
              key={preset}
              type="button"
              variant="outline"
              size="sm"
              disabled={!enabled}
              onClick={() => onChangeExpr(CRON_PRESETS[preset]!)}
            >
              {t(`settings.gitSync.config.cronPresets_${preset}`)}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
