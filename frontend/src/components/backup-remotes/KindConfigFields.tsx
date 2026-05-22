import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { infraCertificatesApi } from "@/lib/infraApi";
import type { Kind } from "./types";

interface KindConfigFieldsProps {
  kind: Kind;
  config: Record<string, string>;
  onChange: (key: string, value: string) => void;
}

export function KindConfigFields({ kind, config, onChange }: KindConfigFieldsProps) {
  const { t } = useTranslation();

  const { data: certificates } = useQuery({
    queryKey: ["infra-certificates"],
    queryFn: () => infraCertificatesApi.list(),
    enabled: kind === "sftp",
  });

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
        {kind === "sftp" && (
          <div>
            <Label>{t("backup_remotes.certificate")}</Label>
            <Select
              value={config["certificate_id"] ?? ""}
              onValueChange={(v) => onChange("certificate_id", v === "__none__" ? "" : v)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t("backup_remotes.certificate_none")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">
                  {t("backup_remotes.certificate_none")}
                </SelectItem>
                {(certificates ?? []).map((cert) => (
                  <SelectItem key={cert.id} value={cert.id}>
                    {cert.name}
                    <span className="ml-2 text-xs text-muted-foreground">
                      {cert.key_type}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
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
