import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  groupVariablesApi,
  type GroupVariable,
} from "@/lib/groupVariablesApi";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfirmDialog } from "@/components/ConfirmDialog";

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
    <div className="border-t pt-3 mt-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <h4 className="text-[13px] font-semibold">
            {t("projects.group_variables_title")}
          </h4>
          <span className="text-[10px] text-muted-foreground">
            ({variables.length})
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowAdd(true)}>
          <Plus className="w-3.5 h-3.5" />
          {t("projects.group_variables_add")}
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground mb-2">
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
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-[11px]">
                {t("projects.group_variables_col_name")}
              </TableHead>
              <TableHead className="text-[11px]">
                {t("projects.group_variables_col_value")}
              </TableHead>
              <TableHead className="text-[11px]">
                {t("projects.group_variables_col_description")}
              </TableHead>
              <TableHead className="w-20" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {variables.map((v) => (
              <TableRow key={v.id}>
                <TableCell className="font-mono text-[12px]">{v.name}</TableCell>
                <TableCell className="font-mono text-[12px] break-all max-w-xs">
                  {v.value || (
                    <span className="text-muted-foreground italic">
                      {t("projects.group_variables_empty_value")}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-[11px] text-muted-foreground">
                  {v.description || "—"}
                </TableCell>
                <TableCell className="text-right space-x-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => setEditTarget(v)}
                    title={t("common.edit")}
                  >
                    <Pencil className="w-3 h-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => setDeleteTarget(v)}
                    title={t("common.delete")}
                  >
                    <Trash2 className="w-3 h-3 text-destructive" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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

  // Reset form quand on rouvre avec un autre initial.
  const dialogKey = `${open}-${initial?.id ?? "new"}`;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      key={dialogKey}
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
