import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Kind } from "./types";

interface KindConfigFieldsProps {
  kind: Kind;
  config: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

export function KindConfigFields({ kind, config, onChange }: KindConfigFieldsProps) {
  const { t } = useTranslation();

  if (kind !== "s3") {
    return (
      <>
        <div>
          <Label>{t("backup_remotes.host")}</Label>
          <Input
            value={config["host"] ?? ""}
            onChange={(e) => onChange("host", e.target.value)}
          />
        </div>
        <div>
          <Label>{t("backup_remotes.port")}</Label>
          <Input
            type="number"
            value={config["port"] ?? (kind === "ftps" ? "21" : "22")}
            onChange={(e) => onChange("port", e.target.value)}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <div>
        <Label>{t("backup_remotes.endpoint_url")}</Label>
        <Input
          value={config["endpoint_url"] ?? ""}
          onChange={(e) => onChange("endpoint_url", e.target.value)}
        />
      </div>
      <div>
        <Label>{t("backup_remotes.bucket")}</Label>
        <Input
          value={config["bucket"] ?? ""}
          onChange={(e) => onChange("bucket", e.target.value)}
        />
      </div>
      <div>
        <Label>{t("backup_remotes.region")}</Label>
        <Input
          value={config["region"] ?? ""}
          onChange={(e) => onChange("region", e.target.value)}
        />
      </div>
    </>
  );
}
