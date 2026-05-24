import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  groupVariablesApi,
  type GroupVariable,
} from "@/lib/groupVariablesApi";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";

function copyViaExec(text: string, container: Element, onDone: () => void) {
  const el = document.createElement("textarea");
  el.value = text;
  el.setAttribute("readonly", "");
  el.style.cssText = "position:absolute;top:0;left:0;width:1px;height:1px;opacity:0;overflow:hidden";
  container.appendChild(el);
  el.focus();
  el.select();
  document.execCommand("copy");
  el.remove();
  onDone();
}

export function GroupVariablesSection({ groupId }: { groupId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data: variables = [], isLoading } = useQuery({
    queryKey: ["group-variables", groupId],
    queryFn: () => groupVariablesApi.list(groupId),
  });

  const [editTarget, setEditTarget] = useState<GroupVariable | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<GroupVariable | null>(null);

  const createMut = useMutation({
    mutationFn: (p: { name: string; value: string; description: string }) =>
      groupVariablesApi.create(groupId, p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["group-variables", groupId] }),
  });
  const updateMut = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: { name?: string; value?: string; description?: string };
    }) => groupVariablesApi.update(groupId, id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["group-variables", groupId] }),
  });
  const removeMut = useMutation({
    mutationFn: (id: string) => groupVariablesApi.remove(groupId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["group-variables", groupId] }),
  });

  return (
    <div className="border-t px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
            {t("projects.group_variables_title")}
          </h4>
          <span className="text-[10px] text-muted-foreground">
            ({variables.length})
          </span>
        </div>
        <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => setShowAdd(true)}>
          <Plus className="w-3 h-3" />
          {t("projects.group_variables_add")}
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground">
        {t("projects.group_variables_hint")}
      </p>

      {isLoading ? (
        <p className="text-[12px] text-muted-foreground italic">
          {t("common.loading")}
        </p>
      ) : variables.length === 0 ? (
        <p className="text-[11px] text-muted-foreground italic">
          {t("projects.group_variables_empty")}
        </p>
      ) : (
        <div className="space-y-2">
          {variables.map((v) => (
            <VariableRow
              key={v.id}
              variable={v}
              onUpdateValue={(value) =>
                updateMut.mutateAsync({ id: v.id, payload: { value } })
              }
              onEdit={() => setEditTarget(v)}
              onDelete={() => setDeleteTarget(v)}
              t={t}
            />
          ))}
        </div>
      )}

      <GroupVariableFormDialog
        open={showAdd}
        initial={null}
        onClose={() => setShowAdd(false)}
        onSubmit={async (payload) => {
          try {
            await createMut.mutateAsync(payload);
            toast.success(t("projects.group_variables_created"));
            setShowAdd(false);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : String(e));
          }
        }}
        t={t}
      />

      <GroupVariableFormDialog
        open={editTarget !== null}
        initial={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={async (payload) => {
          if (!editTarget) return;
          try {
            await updateMut.mutateAsync({ id: editTarget.id, payload });
            toast.success(t("projects.group_variables_updated"));
            setEditTarget(null);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : String(e));
          }
        }}
        t={t}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t("projects.group_variables_delete_title")}
        description={t("projects.group_variables_delete_description", {
          name: deleteTarget?.name ?? "",
        })}
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          if (!deleteTarget) return;
          try {
            await removeMut.mutateAsync(deleteTarget.id);
            toast.success(t("projects.group_variables_deleted"));
            setDeleteTarget(null);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : String(e));
          }
        }}
      />
    </div>
  );
}

// Noms de variables protégées (créées à la création du groupe et essentielles
// au fonctionnement) — le backend refuse la suppression et le bouton Trash
// est caché côté UI. La valeur reste éditable.
const PROTECTED_NAMES = new Set<string>(["RES_NAME"]);

// Une ligne = chip à gauche (avec description en dessous), input au milieu,
// boutons edit/delete à droite. Mêmes proportions que `VarRow` (variables
// d'instance) pour rester cohérent visuellement.
function VariableRow({
  variable,
  onUpdateValue,
  onEdit,
  onDelete,
  t,
}: {
  variable: GroupVariable;
  onUpdateValue: (value: string) => Promise<unknown>;
  onEdit: () => void;
  onDelete: () => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const isProtected = PROTECTED_NAMES.has(variable.name);
  const [draftValue, setDraftValue] = useState(variable.value);
  const [saving, setSaving] = useState(false);
  const isDirty = draftValue !== variable.value;

  // Si la valeur change côté serveur (autre tab, autre user), on resynchronise.
  useEffect(() => {
    setDraftValue(variable.value);
  }, [variable.value]);

  const hasValue = Boolean(draftValue.trim());

  const handleSave = async () => {
    if (!isDirty) return;
    setSaving(true);
    try {
      await onUpdateValue(draftValue);
    } catch (e) {
      setDraftValue(variable.value);
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-start gap-3">
      <div className="w-48 shrink-0 pt-1.5">
        <div className="flex items-center gap-1">
          <Badge
            variant="outline"
            className={`text-[8px] font-mono ${
              hasValue
                ? "border-green-500 text-green-600"
                : "border-blue-400 text-blue-500"
            }`}
          >
            {`\${${variable.name}}`}
          </Badge>
          <button
            type="button"
            title={t("projects.group_variables_copy")}
            className="p-0.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            onClick={(e) => {
              const text = `\${${variable.name}}`;
              const container = (e.currentTarget as HTMLElement).closest('[role="dialog"]') ?? document.body;
              if (navigator.clipboard) {
                navigator.clipboard.writeText(text)
                  .then(() => toast.success(t("projects.group_variables_copied", { name: `\${${variable.name}}` })))
                  .catch(() => copyViaExec(text, container, () => toast.success(t("projects.group_variables_copied", { name: `\${${variable.name}}` }))));
              } else {
                copyViaExec(text, container, () => toast.success(t("projects.group_variables_copied", { name: `\${${variable.name}}` })));
              }
            }}
          >
            <Copy className="w-3 h-3" />
          </button>
        </div>
        {variable.description && (
          <p className="text-[10px] text-muted-foreground mt-0.5">
            {variable.description}
          </p>
        )}
      </div>
      <Input
        value={draftValue}
        onChange={(e) => setDraftValue(e.target.value)}
        placeholder={variable.name}
        className="font-mono text-[12px] flex-1 h-8"
        disabled={saving}
        onBlur={handleSave}
      />
      {isDirty && (
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0 text-green-600 hover:text-green-700"
          onClick={handleSave}
          disabled={saving}
          title={t("common.save")}
        >
          <Save className="w-3.5 h-3.5" />
        </Button>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0"
        onClick={onEdit}
        title={t("common.edit")}
      >
        <Pencil className="w-3 h-3" />
      </Button>
      {!isProtected && (
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={onDelete}
          title={t("common.delete")}
        >
          <Trash2 className="w-3 h-3 text-destructive" />
        </Button>
      )}
    </div>
  );
}

function GroupVariableFormDialog({
  open,
  initial,
  onClose,
  onSubmit,
  t,
}: {
  open: boolean;
  initial: GroupVariable | null;
  onClose: () => void;
  onSubmit: (p: { name: string; value: string; description: string }) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [value, setValue] = useState(initial?.value ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [saving, setSaving] = useState(false);

  // Reset à chaque (ré)ouverture, ou changement de variable cible.
  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setValue(initial?.value ?? "");
    setDescription(initial?.description ?? "");
    setSaving(false);
  }, [open, initial]);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {initial
              ? t("projects.group_variables_edit_title")
              : t("projects.group_variables_add_title")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">
              {t("projects.group_variables_col_name")}
            </Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="PUBLIC_HOSTNAME"
              className="mt-1 font-mono"
              autoFocus
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              {t("projects.group_variables_name_hint")}
            </p>
          </div>
          <div>
            <Label className="text-[11px]">
              {t("projects.group_variables_col_value")}
            </Label>
            <Input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="outline.yoops.org    ou    ${vault://api1:token}"
              className="mt-1 font-mono"
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              {t("projects.group_variables_value_hint")}
            </p>
          </div>
          <div>
            <Label className="text-[11px]">
              {t("projects.group_variables_col_description")}
            </Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("projects.group_variables_description_placeholder")}
              className="mt-1"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit({ name: name.trim(), value, description });
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? "..." : t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
