import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { api } from "@/lib/api";

// ─── Types ──────────────────────────────────────────────────────────────────

interface Connection {
  id: string;
  name: string;
  kind: "sftp" | "ftps" | "s3";
  config: Record<string, string>;
  has_credentials: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Page ────────────────────────────────────────────────────────────────────

export function RemoteBackupConnectionsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [modalConn, setModalConn] = useState<Connection | null | "new">(null);
  const [deleteTarget, setDeleteTarget] = useState<Connection | null>(null);

  const { data: connections = [] } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () =>
      api
        .get<Connection[]>("/admin/backup-remotes")
        .then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/admin/backup-remotes/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["backup-remotes"] });
    },
  });

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">{t("backup_remotes.title")}</h1>
        <Button onClick={() => setModalConn("new")}>
          {t("backup_remotes.add")}
        </Button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4">{t("backup_remotes.name")}</th>
            <th className="pr-4">{t("backup_remotes.kind")}</th>
            <th className="pr-4">{t("backup_remotes.host")}</th>
            <th className="pr-4">{t("backup_remotes.paths")}</th>
            <th>{t("backup_remotes.has_credentials")}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {connections.map((c) => (
            <tr
              key={c.id}
              className="border-b hover:bg-muted/50 cursor-pointer"
              onClick={() => setModalConn(c)}
            >
              <td className="py-2 pr-4 font-medium">{c.name}</td>
              <td className="pr-4 uppercase text-xs">{c.kind}</td>
              <td className="pr-4">{c.config["host"] ?? "—"}</td>
              <td className="pr-4 text-xs text-muted-foreground">
                {[
                  c.config["remote_path_snapshots"],
                  c.config["remote_path_full"],
                  c.config["prefix_snapshots"],
                  c.config["prefix_full"],
                ]
                  .filter(Boolean)
                  .join(" / ") || t("backup_remotes.not_configured")}
              </td>
              <td>{c.has_credentials ? "✓" : "✗"}</td>
              <td
                onClick={(e) => e.stopPropagation()}
              >
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setDeleteTarget(c)}
                >
                  ×
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {modalConn !== null && (
        <ConnectionModal
          connection={modalConn === "new" ? null : modalConn}
          onClose={() => setModalConn(null)}
          onSaved={() => {
            void qc.invalidateQueries({ queryKey: ["backup-remotes"] });
            setModalConn(null);
          }}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("backup_remotes.delete_confirm")}
        description={deleteTarget?.name ?? ""}
        destructive
        onConfirm={() => {
          if (deleteTarget) {
            deleteMutation.mutate(deleteTarget.id);
          }
        }}
      />
    </div>
  );
}

// ─── ConnectionModal ──────────────────────────────────────────────────────────

interface ConnectionModalProps {
  connection: Connection | null;
  onClose: () => void;
  onSaved: () => void;
}

interface TestResult {
  ok: boolean;
  msg?: string;
}

function ConnectionModal({
  connection,
  onClose,
  onSaved,
}: ConnectionModalProps) {
  const { t } = useTranslation();
  const isEdit = connection !== null;
  const [kind, setKind] = useState<string>(connection?.kind ?? "sftp");
  const [name, setName] = useState(connection?.name ?? "");
  const [config, setConfig] = useState<Record<string, string>>(
    connection?.config ?? {}
  );
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [testResults, setTestResults] = useState<Record<string, TestResult>>(
    {}
  );

  const saveMutation = useMutation({
    mutationFn: () => {
      const credentials =
        username || password
          ? kind === "s3"
            ? { access_key_id: username, secret_access_key: password }
            : { username, password }
          : undefined;
      if (isEdit) {
        return api.patch(`/admin/backup-remotes/${connection.id}`, {
          name,
          config,
          credentials,
        });
      }
      return api.post("/admin/backup-remotes", {
        name,
        kind,
        config,
        credentials,
      });
    },
    onSuccess: onSaved,
  });

  const handleTest = async (pathKey: string) => {
    const path = config[pathKey] ?? "";
    if (!path) return;
    const useVault = isEdit && !username;
    const url = useVault
      ? `/admin/backup-remotes/${connection.id}/test`
      : "/admin/backup-remotes/test";
    const body = useVault
      ? { path, config }
      : {
          kind,
          config,
          credentials:
            kind === "s3"
              ? { access_key_id: username, secret_access_key: password }
              : { username, password },
          path,
        };
    try {
      const res = await api.post<{ ok: boolean; message?: string }>(url, body);
      setTestResults((r) => ({
        ...r,
        [pathKey]: { ok: res.data.ok, msg: res.data.message },
      }));
    } catch {
      setTestResults((r) => ({
        ...r,
        [pathKey]: { ok: false, msg: "request failed" },
      }));
    }
  };

  const pathKeys =
    kind === "s3"
      ? ["prefix_snapshots", "prefix_full"]
      : ["remote_path_snapshots", "remote_path_full"];

  const pathLabelKey = (key: string): string =>
    key === "prefix_snapshots" || key === "remote_path_snapshots"
      ? "path_snapshots"
      : "path_full";

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? connection.name : t("backup_remotes.add")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>{t("backup_remotes.name")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          {!isEdit && (
            <div>
              <Label>{t("backup_remotes.kind")}</Label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sftp">
                    {t("backup_remotes.kind_sftp")}
                  </SelectItem>
                  <SelectItem value="ftps">
                    {t("backup_remotes.kind_ftps")}
                  </SelectItem>
                  <SelectItem value="s3">
                    {t("backup_remotes.kind_s3")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}

          {kind !== "s3" && (
            <>
              <div>
                <Label>{t("backup_remotes.host")}</Label>
                <Input
                  value={config["host"] ?? ""}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, host: e.target.value }))
                  }
                />
              </div>
              <div>
                <Label>{t("backup_remotes.port")}</Label>
                <Input
                  type="number"
                  value={config["port"] ?? (kind === "ftps" ? "21" : "22")}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, port: e.target.value }))
                  }
                />
              </div>
            </>
          )}

          {kind === "s3" && (
            <>
              <div>
                <Label>{t("backup_remotes.endpoint_url")}</Label>
                <Input
                  value={config["endpoint_url"] ?? ""}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, endpoint_url: e.target.value }))
                  }
                />
              </div>
              <div>
                <Label>{t("backup_remotes.bucket")}</Label>
                <Input
                  value={config["bucket"] ?? ""}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, bucket: e.target.value }))
                  }
                />
              </div>
              <div>
                <Label>{t("backup_remotes.region")}</Label>
                <Input
                  value={config["region"] ?? ""}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, region: e.target.value }))
                  }
                />
              </div>
            </>
          )}

          {pathKeys.map((key) => {
            const result = testResults[key];
            return (
              <div key={key}>
                <Label>{t(`backup_remotes.${pathLabelKey(key)}`)}</Label>
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

          <div
            className={`rounded-md border px-3 py-2 text-sm ${
              isEdit && connection.has_credentials
                ? "border-border bg-muted/50 text-foreground"
                : "border-destructive/50 bg-destructive/10 text-destructive"
            }`}
          >
            {isEdit && connection.has_credentials
              ? t("backup_remotes.credentials_ok")
              : t("backup_remotes.credentials_missing")}
          </div>

          <div>
            <Label>
              {kind === "s3"
                ? t("backup_remotes.access_key_id")
                : t("backup_remotes.username")}
            </Label>
            <Input
              placeholder={
                isEdit && connection?.has_credentials ? "••••••••" : ""
              }
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>

          <div>
            <Label>
              {kind === "s3"
                ? t("backup_remotes.secret_access_key")
                : t("backup_remotes.password")}
            </Label>
            <Input
              type="password"
              placeholder={
                isEdit && connection?.has_credentials ? "••••••••" : ""
              }
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

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
        </div>
      </DialogContent>
    </Dialog>
  );
}
