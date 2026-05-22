import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2, X, Check, Lock, LockOpen } from "lucide-react";
import { toast } from "sonner";
import { useNamedTypeEnvVars, useNamedTypeEnvVarsMutations } from "@/hooks/useInfraEnvVars";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

interface NewRow {
  name: string;
  description: string;
  is_secret: boolean;
}

export function NamedTypeEnvVarsSection({ namedTypeId }: { namedTypeId: string }) {
  const { t } = useTranslation();
  const { data: envVars = [], isLoading } = useNamedTypeEnvVars(namedTypeId);
  const { create, update, remove } = useNamedTypeEnvVarsMutations(namedTypeId);
  const [newRow, setNewRow] = useState<NewRow | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);

  async function handleAdd() {
    if (!newRow) return;
    if (!NAME_RE.test(newRow.name)) {
      toast.error(t("infra.env_var_invalid_name"));
      return;
    }
    try {
      await create.mutateAsync({
        name: newRow.name,
        description: newRow.description,
        position: envVars.length,
        is_secret: newRow.is_secret,
      });
      setNewRow(null);
      toast.success(t("infra.env_var_added"));
    } catch {
      toast.error(t("infra.env_var_add_error"));
    }
  }

  async function handleToggleSecret(id: string, current: boolean) {
    try {
      await update.mutateAsync({ id, payload: { is_secret: !current } });
    } catch {
      toast.error(t("infra.env_var_add_error"));
    }
  }

  const deleteTarget = envVars.find((v) => v.id === deleteTargetId);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{t("infra.env_vars_title")}</p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setNewRow({ name: "", description: "", is_secret: false })}
        >
          <Plus className="w-3.5 h-3.5 mr-1" />
          {t("infra.env_var_add_button")}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-xs text-muted-foreground">…</p>
      ) : envVars.length === 0 && !newRow ? (
        <p className="text-xs text-muted-foreground italic">{t("infra.env_vars_empty")}</p>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-xs">{t("infra.env_var_col_name")}</th>
                <th className="text-left px-3 py-2 font-medium text-xs">{t("infra.env_var_col_description")}</th>
                <th className="text-center px-3 py-2 font-medium text-xs w-16">{t("infra.env_var_col_secret")}</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {envVars.map((v) => (
                <tr key={v.id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{v.name}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{v.description}</td>
                  <td className="px-2 py-1 text-center">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6"
                      title={v.is_secret ? t("infra.env_var_secret_yes") : t("infra.env_var_secret_no")}
                      onClick={() => void handleToggleSecret(v.id, v.is_secret)}
                    >
                      {v.is_secret
                        ? <Lock className="w-3.5 h-3.5 text-amber-500" />
                        : <LockOpen className="w-3.5 h-3.5 text-muted-foreground" />}
                    </Button>
                  </td>
                  <td className="px-2 py-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6"
                      onClick={() => setDeleteTargetId(v.id)}
                    >
                      <Trash2 className="w-3 h-3 text-destructive" />
                    </Button>
                  </td>
                </tr>
              ))}
              {newRow && (
                <tr className="border-t bg-muted/20">
                  <td className="px-2 py-1">
                    <Input
                      className="h-7 text-xs font-mono"
                      placeholder={t("infra.env_var_name_placeholder")}
                      value={newRow.name}
                      onChange={(e) => setNewRow({ ...newRow, name: e.target.value.toUpperCase() })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void handleAdd();
                        if (e.key === "Escape") setNewRow(null);
                      }}
                      autoFocus
                    />
                  </td>
                  <td className="px-2 py-1">
                    <Input
                      className="h-7 text-xs"
                      placeholder={t("infra.env_var_description_placeholder")}
                      value={newRow.description}
                      onChange={(e) => setNewRow({ ...newRow, description: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-1 text-center">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6"
                      title={newRow.is_secret ? t("infra.env_var_secret_yes") : t("infra.env_var_secret_no")}
                      onClick={() => setNewRow({ ...newRow, is_secret: !newRow.is_secret })}
                    >
                      {newRow.is_secret
                        ? <Lock className="w-3.5 h-3.5 text-amber-500" />
                        : <LockOpen className="w-3.5 h-3.5 text-muted-foreground" />}
                    </Button>
                  </td>
                  <td className="px-2 py-1">
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="w-6 h-6"
                        onClick={() => void handleAdd()}
                      >
                        <Check className="w-3 h-3 text-green-600" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="w-6 h-6"
                        onClick={() => setNewRow(null)}
                      >
                        <X className="w-3 h-3" />
                      </Button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={deleteTargetId !== null}
        onOpenChange={(o) => {
          if (!o) setDeleteTargetId(null);
        }}
        title={t("infra.env_var_delete_title")}
        description={t("infra.env_var_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (!deleteTargetId) return;
          try {
            await remove.mutateAsync(deleteTargetId);
            setDeleteTargetId(null);
            toast.success(t("infra.env_var_deleted"));
          } catch {
            toast.error(t("infra.env_var_delete_error"));
          }
        }}
      />
    </div>
  );
}
