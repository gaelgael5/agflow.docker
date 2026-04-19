import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useSecrets } from "@/hooks/useSecrets";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { SecretForm } from "@/components/SecretForm";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import type { EnvVarStatus as EnvVarStatusT } from "@/lib/secretsApi";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { secretsApi, type SecretCreate, type SecretSummary } from "@/lib/secretsApi";

export function SecretsPage() {
  const { t } = useTranslation();
  const { secrets, isLoading, createMutation, updateMutation, deleteMutation } = useSecrets();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const envStatus = useEnvVarStatuses(
    (secrets ?? []).map((s) => s.var_name),
  );

  async function handleCreate(payload: SecretCreate) {
    setError(null);
    try {
      await createMutation.mutateAsync(payload);
      setShowForm(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      setError(
        status === 409
          ? t("secrets.error_duplicate")
          : t("secrets.error_generic"),
      );
    }
  }

  function handleDelete(secret: SecretSummary) {
    setDeleteTarget({ id: secret.id, name: secret.var_name });
  }

  return (
    <PageShell>
      <PageHeader
        title={t("secrets.page_title")}
        subtitle={t("secrets.page_subtitle")}
        actions={
          <Button onClick={() => setShowForm(true)} disabled={showForm}>
            <Plus className="w-4 h-4" />
            {t("secrets.add_button")}
          </Button>
        }
      />

      {showForm && (
        <Card className="mb-6">
          <CardContent className="pt-5">
            <SecretForm
              mode="create"
              onSubmit={handleCreate}
              onCancel={() => {
                setShowForm(false);
                setError(null);
              }}
            />
            {error && (
              <p role="alert" className="text-destructive text-[12px] mt-2">
                {error}
              </p>
            )}
          </CardContent>
        </Card>
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
                <TableHead>{t("secrets.col_value")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("secrets.col_scope")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("secrets.col_used_by")}</TableHead>
                <TableHead className="text-right">
                  {t("secrets.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {secrets?.map((secret) => (
                <SecretRow
                  key={secret.id}
                  secret={secret}
                  status={envStatus.data?.[secret.var_name]}
                  onDelete={() => handleDelete(secret)}
                  onUpdate={async (value) => {
                    await updateMutation.mutateAsync({ id: secret.id, payload: { value } });
                  }}
                  t={t}
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
        }}
      />
    </PageShell>
  );
}

// ── Secret row with reveal, edit, copy ────────────────────────

function SecretRow({
  secret,
  status,
  onDelete,
  onUpdate,
  t,
}: {
  secret: SecretSummary;
  status: EnvVarStatusT | undefined;
  onDelete: () => void;
  onUpdate: (value: string) => Promise<void>;
  t: (key: string) => string;
}) {
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
      toast.success(t("secrets.updated"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-1.5">
          <EnvVarStatus name={secret.var_name} status={status} />
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            title={t("secrets.copy_key")}
            onClick={() => { void navigator.clipboard.writeText(secret.var_name); toast.success(`${secret.var_name} copié`); }}
          >
            <Copy className="w-3 h-3 text-muted-foreground" />
          </Button>
        </div>
      </TableCell>
      <TableCell>
        {editing ? (
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              className="flex-1 text-[12px] font-mono border rounded px-2 py-1 bg-background"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSaveEdit();
                if (e.key === "Escape") setEditing(false);
              }}
            />
            <Button size="sm" onClick={() => void handleSaveEdit()} disabled={loading}>
              {t("secrets.save_edit")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
              {t("secrets.cancel_edit")}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <code className="text-[12px]">{revealed ?? t("secrets.value_masked")}</code>
            {revealed === null ? (
              <Button variant="ghost" size="sm" onClick={() => void handleReveal()} disabled={loading}>
                {t("secrets.reveal")}
              </Button>
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title={t("secrets.copy_value")}
                  onClick={() => { void navigator.clipboard.writeText(revealed); toast.success(t("secrets.value_copied")); }}
                >
                  <Copy className="w-3 h-3 text-muted-foreground" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title={t("secrets.edit_value")}
                  onClick={() => { setEditValue(revealed); setEditing(true); }}
                >
                  <Pencil className="w-3 h-3 text-muted-foreground" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setRevealed(null)}>
                  {t("secrets.hide")}
                </Button>
              </>
            )}
          </div>
        )}
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <Badge variant="secondary">
          {secret.scope === "global" ? t("secrets.scope_global") : t("secrets.scope_agent")}
        </Badge>
      </TableCell>
      <TableCell className="hidden md:table-cell text-muted-foreground text-[12px]">
        {secret.used_by.length === 0 ? t("secrets.none_used_by") : secret.used_by.join(", ")}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label={t("secrets.delete")}>
            <Trash2 className="w-3.5 h-3.5 text-destructive" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}
