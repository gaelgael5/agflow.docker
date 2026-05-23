import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { VaultSecretPicker } from "./VaultSecretPicker";
import { restoreApi, type VaultSecretItem } from "@/lib/restoreApi";

type ConnectionType = "sftp" | "s3" | "ftps" | "gdrive";

interface ConnectionConfig {
  type: ConnectionType;
  manual: Record<string, string>;
  vault: Record<string, string>;
}

interface RemoteConnectionStepProps {
  vaultUrl: string;
  vaultApiKey: string;
  secrets: VaultSecretItem[];
  onDone: (config: ConnectionConfig) => void;
}

const FIELDS: Record<
  ConnectionType,
  {
    manual: { key: string; label: string; placeholder?: string; required?: boolean }[];
    vault: { key: string; label: string; optional?: boolean; prefix?: string }[];
  }
> = {
  sftp: {
    manual: [
      { key: "host", label: "Host", placeholder: "192.168.1.1", required: true },
      { key: "port", label: "Port", placeholder: "22" },
      { key: "path", label: "Répertoire racine", placeholder: "/backups" },
    ],
    vault: [
      { key: "username", label: "Nom d'utilisateur", prefix: "remote-backups" },
      { key: "password", label: "Mot de passe", optional: true, prefix: "remote-backups" },
      { key: "private_key", label: "Clé privée SSH", optional: true, prefix: "certificates" },
      { key: "passphrase", label: "Passphrase clé", optional: true, prefix: "remote-backups" },
    ],
  },
  s3: {
    manual: [
      { key: "bucket", label: "Bucket", required: true },
      { key: "region", label: "Région", placeholder: "eu-west-1", required: true },
      { key: "prefix", label: "Préfixe", placeholder: "backups/" },
    ],
    vault: [
      { key: "access_key_id", label: "Access Key ID" },
      { key: "secret_access_key", label: "Secret Access Key" },
    ],
  },
  ftps: {
    manual: [
      { key: "host", label: "Host", required: true },
      { key: "port", label: "Port", placeholder: "21" },
      { key: "path", label: "Répertoire racine", placeholder: "/backups" },
    ],
    vault: [
      { key: "username", label: "Nom d'utilisateur" },
      { key: "password", label: "Mot de passe" },
    ],
  },
  gdrive: {
    manual: [],
    vault: [{ key: "credentials_json", label: "Credentials JSON" }],
  },
};

export function RemoteConnectionStep({
  vaultUrl,
  vaultApiKey,
  secrets,
  onDone,
}: RemoteConnectionStepProps): JSX.Element {
  const { t } = useTranslation();
  const [type, setType] = useState<ConnectionType>("sftp");
  const [manual, setManual] = useState<Record<string, string>>({});
  const [vaultMap, setVaultMap] = useState<Record<string, string>>({});

  const fields = FIELDS[type]!;

  function setManualField(key: string, value: string) {
    setManual((prev) => ({ ...prev, [key]: value }));
  }

  function setVaultField(key: string, value: string) {
    setVaultMap((prev) => ({ ...prev, [key]: value }));
  }

  function secretsForField(prefix?: string): VaultSecretItem[] {
    if (!prefix) return secrets;
    return secrets.filter((s) => s.name.startsWith(prefix + "/"));
  }

  const testMutation = useMutation({
    mutationFn: () =>
      restoreApi.browse({
        connection_type: type,
        manual_fields: { ...manual, path: manual["path"] ?? "/" },
        vault_mappings: vaultMap,
        vault: { url: vaultUrl, api_key: vaultApiKey },
        path: manual["path"] ?? "/",
      }),
    onSuccess: () => {
      onDone({ type, manual, vault: vaultMap });
    },
    onError: () => {
      toast.error(t("restore.connection_test_error"));
    },
  });

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <Label>{t("restore.connection_type_label")}</Label>
        <Select
          value={type}
          onValueChange={(v) => {
            setType(v as ConnectionType);
            setManual({});
            setVaultMap({});
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sftp">SFTP</SelectItem>
            <SelectItem value="s3">S3</SelectItem>
            <SelectItem value="ftps">FTPS</SelectItem>
            <SelectItem value="gdrive">Google Drive</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {fields.manual.map((f) => (
        <div key={f.key} className="space-y-1">
          <Label htmlFor={`manual-${f.key}`}>{f.label}</Label>
          <Input
            id={`manual-${f.key}`}
            placeholder={f.placeholder}
            value={manual[f.key] ?? ""}
            onChange={(e) => setManualField(f.key, e.target.value)}
          />
        </div>
      ))}

      {fields.vault.map((f) => (
        <VaultSecretPicker
          key={f.key}
          label={f.label}
          secrets={secretsForField(f.prefix)}
          value={vaultMap[f.key] ?? ""}
          onChange={(v) => setVaultField(f.key, v)}
          optional={f.optional}
        />
      ))}

      <Button
        onClick={() => testMutation.mutate()}
        disabled={testMutation.isPending}
      >
        {testMutation.isPending ? t("common.loading") : t("restore.btn_test_connection")}
      </Button>
    </div>
  );
}
