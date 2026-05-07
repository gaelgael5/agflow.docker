import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useSecrets } from "@/hooks/useSecrets";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { secretsApi, type PlatformSecretSummary } from "@/lib/secretsApi";

type FormMode = "vault" | "env" | null;

export function SecretsPage() {
  const { t } = useTranslation();
  const { secrets, isLoading, createVaultMutation, createEnvMutation, updateMutation, deleteMutation } = useSecrets();
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PlatformSecretSummary | null>(null);

  async function handleCreateVault(name: string, value: string) {
    setFormError(null);
    try {
      await createVaultMutation.mutateAsync({ name, value });
      setFormMode(null);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      setFormError(status === 409 ? t("secrets.error_duplicate") : t("secrets.error_generic"));
    }
  }

  async function handleCreateEnv(name: string, value: string) {
    setFormError(null);
    try {
      await createEnvMutation.mutateAsync({ name, value });
      setFormMode(null);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      setFormError(status === 409 ? t("secrets.error_duplicate") : t("secrets.error_generic"));
    }
  }

  function openForm(mode: FormMode) {
    setFormMode(mode);
    setFormError(null);
  }

  return (
    <PageShell>
      <PageHeader
        title={t("secrets.page_title")}
        subtitle={t("secrets.page_subtitle")}
        actions={
          <div className="flex gap-2">
            <Button onClick={() => openForm("vault")} disabled={formMode !== null} variant="default">
              {t("secrets.add_vault_button")}
            </Button>
            <Button onClick={() => openForm("env")} disabled={formMode !== null} variant="outline">
              {t("secrets.add_env_button")}
            </Button>
          </div>
        }
      />

      {formMode === "vault" && (
        <SecretFormCard
          title={t("secrets.form_vault_title")}
          type="vault"
          error={formError}
          onSubmit={handleCreateVault}
          onCancel={() => { setFormMode(null); setFormError(null); }}
        />
      )}

      {formMode === "env" && (
        <SecretFormCard
          title={t("secrets.form_env_title")}
          type="env"
          error={formError}
          onSubmit={handleCreateEnv}
          onCancel={() => { setFormMode(null); setFormError(null); }}
        />
      )}

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-6 w-2/5" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("secrets.col_name")}</TableHead>
                <TableHead>{t("secrets.col_type")}</TableHead>
                <TableHead>{t("secrets.col_key")}</TableHead>
                <TableHead>{t("secrets.col_value")}</TableHead>
                <TableHead className="text-right">{t("secrets.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(secrets ?? []).map((secret) => (
                <SecretRow
                  key={secret.id}
                  secret={secret}
                  onDelete={() => setDeleteTarget(secret)}
                  onUpdate={async (value) => {
                    await updateMutation.mutateAsync({ id: secret.id, payload: { value } });
                    toast.success(t("secrets.updated"));
                  }}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("secrets.confirm_delete_title")}
        description={t("secrets.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
          setDeleteTarget(null);
        }}
      />
    </PageShell>
  );
}

// ── Inline creation form ───────────────────────────────────────

const VAULT_API_KEY_ID = "HARPOCRATE_KEY";

function buildPreview(type: "vault" | "env", name: string): string {
  const upper = name.trim().toUpperCase();
  if (!upper) return type === "vault" ? `\${vault://${VAULT_API_KEY_ID}:…}` : `\${env://…}`;
  return type === "vault"
    ? `\${vault://${VAULT_API_KEY_ID}:${upper}}`
    : `\${env://${upper}}`;
}

function SecretFormCard({
  title,
  type,
  error,
  onSubmit,
  onCancel,
}: {
  title: string;
  type: "vault" | "env";
  error: string | null;
  onSubmit: (name: string, value: string) => Promise<void>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);

  const preview = buildPreview(type, name);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await onSubmit(name, value);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="secret-name">{t("secrets.form_name_label")}</Label>
              <Input
                id="secret-name"
                placeholder={t("secrets.form_name_placeholder")}
                value={name}
                onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))}
                required
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("secrets.form_preview_label")}</Label>
              <div className="flex items-center gap-1.5">
                <code className="flex-1 text-[12px] font-mono bg-muted px-2 py-1.5 rounded border truncate">
                  {preview}
                </code>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  title={t("secrets.copy_ref")}
                  onClick={() => { void navigator.clipboard.writeText(preview); toast.success(t("secrets.ref_copied")); }}
                >
                  <Copy className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="secret-value">{t("secrets.form_value_label")}</Label>
            <Input
              id="secret-value"
              type="password"
              placeholder={t("secrets.form_value_placeholder")}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              required={type === "vault"}
            />
          </div>

          {error && (
            <p role="alert" className="text-destructive text-[12px]">{error}</p>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={loading || !name}>
              {t("secrets.form_save")}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("secrets.form_cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// ── Table row ──────────────────────────────────────────────────

function SecretRow({
  secret,
  onDelete,
  onUpdate,
}: {
  secret: PlatformSecretSummary;
  onDelete: () => void;
  onUpdate: (value: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [revealed, setRevealed] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleReveal() {
    setLoading(true);
    try {
      const res = await secretsApi.reveal(secret.id);
      setRevealed(res.value);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveEdit() {
    setLoading(true);
    try {
      await onUpdate(editValue);
      setRevealed(editValue);
      setEditing(false);
    } finally {
      setLoading(false);
    }
  }

  return (
    <TableRow>
      <TableCell className="font-mono text-[13px]">{secret.name}</TableCell>
      <TableCell>
        <Badge variant={secret.type === "vault" ? "default" : "secondary"}>
          {t(`secrets.type_${secret.type}`)}
        </Badge>
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1">
          <code className="text-[11px] text-muted-foreground truncate max-w-[280px]">{secret.key}</code>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            title={t("secrets.copy_ref")}
            onClick={() => { void navigator.clipboard.writeText(secret.key); toast.success(t("secrets.ref_copied")); }}
          >
            <Copy className="w-2.5 h-2.5" />
          </Button>
        </div>
      </TableCell>
      <TableCell>
        {editing ? (
          <div className="flex items-center gap-1.5">
            <Input
              className="h-7 text-[12px] font-mono w-48"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSaveEdit();
                if (e.key === "Escape") setEditing(false);
              }}
            />
            <Button size="sm" className="h-7" onClick={() => void handleSaveEdit()} disabled={loading}>
              {t("secrets.save_edit")}
            </Button>
            <Button size="sm" className="h-7" variant="outline" onClick={() => setEditing(false)}>
              {t("secrets.cancel_edit")}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <code className="text-[12px]">
              {revealed !== null ? (revealed || t("secrets.value_empty")) : t("secrets.value_masked")}
            </code>
            {revealed === null ? (
              <Button variant="ghost" size="sm" className="h-6 text-[12px]" onClick={() => void handleReveal()} disabled={loading}>
                {t("secrets.reveal")}
              </Button>
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  title={t("secrets.copy_value")}
                  onClick={() => { void navigator.clipboard.writeText(revealed); toast.success(t("secrets.value_copied")); }}
                >
                  <Copy className="w-2.5 h-2.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  title={t("secrets.edit_value")}
                  onClick={() => { setEditValue(revealed); setEditing(true); }}
                >
                  <Pencil className="w-2.5 h-2.5" />
                </Button>
                <Button variant="ghost" size="sm" className="h-6 text-[12px]" onClick={() => setRevealed(null)}>
                  {t("secrets.hide")}
                </Button>
              </>
            )}
          </div>
        )}
      </TableCell>
      <TableCell className="text-right">
        <Button variant="ghost" size="icon" onClick={onDelete} aria-label={t("secrets.delete")}>
          <Trash2 className="w-3.5 h-3.5 text-destructive" />
        </Button>
      </TableCell>
    </TableRow>
  );
}
