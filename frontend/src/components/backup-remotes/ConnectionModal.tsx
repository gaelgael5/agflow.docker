import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useHarpocrateVaults } from "@/hooks/useHarpocrateVaults";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Connection, Kind } from "./types";
import { KindConfigFields } from "./KindConfigFields";
import { CredentialsFields } from "./CredentialsFields";
import { GDriveFields } from "./GDriveFields";

// ─── Types ───────────────────────────────────────────────────────────────────

export type { Connection } from "./types";

interface TestResult {
  ok: boolean;
  msg?: string;
}

// ─── Props ────────────────────────────────────────────────────────────────────

export interface ConnectionModalProps {
  connection: Connection | null;
  onClose: () => void;
  onSaved: () => void;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ConnectionModal({
  connection,
  onClose,
  onSaved,
}: ConnectionModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isEdit = connection !== null;

  const { vaults, defaultVault } = useHarpocrateVaults();
  const [kind, setKind] = useState<Kind>(connection?.kind ?? "sftp");
  const [name, setName] = useState(connection?.name ?? "");
  const [config, setConfig] = useState<Record<string, string>>(
    connection?.config ?? {}
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [vaultName, setVaultName] = useState("");
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  const effectiveVaultName = vaultName || defaultVault?.name || vaults[0]?.name || "";
  const vaultHint = t("backup_remotes.credentials_vault_path", {
    vault: effectiveVaultName || "<vault>",
  });

  const useVault = isEdit && !username;

  const buildCredentials = () => {
    if (!username && !password) return undefined;
    if (kind === "s3") return { access_key_id: username, secret_access_key: password };
    return { username, password };
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const finalConfig = {
        ...config,
        ...(kind !== "s3" && !config["port"]
          ? { port: kind === "ftps" ? "21" : "22" }
          : {}),
      };
      if (isEdit) {
        return api.patch(`/admin/backup-remotes/${connection.id}`, {
          name,
          config: finalConfig,
          credentials: buildCredentials(),
        });
      }
      return api.post("/admin/backup-remotes", {
        name,
        kind,
        config: finalConfig,
        credentials: buildCredentials(),
        vault_name: effectiveVaultName || undefined,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["backup-remotes"] });
      onSaved();
    },
  });

  const handleTest = async (pathKey: string) => {
    const path = config[pathKey] ?? "";
    if (!path) return;
    const hasCredentials = Boolean(username && password);
    if (!useVault && !hasCredentials) return;

    const url = useVault
      ? `/admin/backup-remotes/${connection.id}/test`
      : "/admin/backup-remotes/test";
    const body = useVault
      ? { path, config }
      : { kind, config, credentials: buildCredentials(), path };
    try {
      const res = await api.post<{ ok: boolean; message?: string }>(url, body);
      setTestResults((r) => ({
        ...r,
        [pathKey]: { ok: res.data.ok, msg: res.data.message },
      }));
    } catch {
      setTestResults((r) => ({
        ...r,
        [pathKey]: { ok: false, msg: t("backup_remotes.test_request_failed") },
      }));
    }
  };

  const pathKeys = kind === "s3" ? ["prefix_full"] : ["remote_path_full"];

  const handleConfigChange = (key: string, value: string) =>
    setConfig((c) => ({ ...c, [key]: value }));

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-[44rem]" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {isEdit ? connection.name : t("backup_remotes.add")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {!isEdit && (
            <div>
              <Label>{t("backup_remotes.kind")}</Label>
              <Select
                value={kind}
                onValueChange={(v) => {
                  setKind(v as Kind);
                  setConfig({});
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sftp">{t("backup_remotes.kind_sftp")}</SelectItem>
                  <SelectItem value="ftps">{t("backup_remotes.kind_ftps")}</SelectItem>
                  <SelectItem value="s3">{t("backup_remotes.kind_s3")}</SelectItem>
                  <SelectItem value="gdrive">{t("backups.gdrive.kindLabel")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {kind === "gdrive" && !isEdit && (
            <GDriveFields
              onCompleted={() => {
                toast.success(t("backups.gdrive.phaseConfirmedTitle"));
                onSaved();
                onClose();
              }}
              onCancel={onClose}
            />
          )}

          {kind === "gdrive" && isEdit && (
            <p className="text-sm text-muted-foreground">
              {t("backups.gdrive.btnReauthorize")} : disponible depuis la liste des connexions.
            </p>
          )}

          {kind !== "gdrive" && (
            <>
              <div>
                <Label>{t("backup_remotes.name")}</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} />
              </div>

              <KindConfigFields kind={kind} config={config} onChange={handleConfigChange} />

              {pathKeys.map((key) => {
                const result = testResults[key];
                const pathFilled = Boolean(config[key]);
                const hasCertAuth = kind === "sftp" && Boolean(config["certificate_id"]);
                const hasCredentials = hasCertAuth
                  ? Boolean(username)
                  : Boolean(username && password);
                const testDisabled = !pathFilled || (!useVault && !hasCredentials);
                return (
                  <div key={key}>
                    <Label>{t("backup_remotes.path_full")}</Label>
                    <div className="flex gap-2">
                      <Input
                        value={config[key] ?? ""}
                        onChange={(e) =>
                          setConfig((c) => ({ ...c, [key]: e.target.value }))
                        }
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={testDisabled}
                        onClick={() => void handleTest(key)}
                      >
                        {t("backup_remotes.test")}
                      </Button>
                    </div>
                    {result !== undefined && (
                      <p
                        className={`text-xs mt-0.5 ${result.ok ? "text-green-600" : "text-red-600"}`}
                      >
                        {result.ok
                          ? t("backup_remotes.test_ok")
                          : `${t("backup_remotes.test_fail")}: ${result.msg ?? ""}`}
                      </p>
                    )}
                  </div>
                );
              })}

              {!isEdit && vaults.length > 0 && (
                <div>
                  <Label>{t("backup_remotes.vault")}</Label>
                  <Select value={effectiveVaultName} onValueChange={setVaultName}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {vaults.map((v) => (
                        <SelectItem key={v.id} value={v.name}>
                          {v.name}
                          {v.is_default ? ` ${t("backup_remotes.vault_default")}` : ""}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              <CredentialsFields
                kind={kind}
                username={username}
                password={password}
                hasExisting={isEdit && connection.has_credentials}
                onChangeUsername={setUsername}
                onChangePassword={setPassword}
                vaultHint={vaultHint}
              />

              {saveMutation.isError && (
                <p className="text-xs text-destructive">
                  {t("common.error_saving")}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={onClose}>
                  {t("common.cancel")}
                </Button>
                <Button
                  onClick={() => saveMutation.mutate()}
                  disabled={saveMutation.isPending}
                >
                  {t("backup_remotes.save")}
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
