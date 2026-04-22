import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCode, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  scriptsApi,
  type ScriptRow,
  type ScriptSummary,
} from "@/lib/scriptsApi";
import { useInfraNamedTypes } from "@/hooks/useInfra";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ShellEditor } from "@/components/ShellEditor";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const selectClass = "mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm";

export function ScriptsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const listQuery = useQuery({ queryKey: ["scripts"], queryFn: () => scriptsApi.list() });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const scripts = listQuery.data ?? [];

  useEffect(() => {
    if (!selectedId && scripts.length > 0) setSelectedId(scripts[0]!.id);
  }, [scripts, selectedId]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => scriptsApi.remove(id),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      if (selectedId === id) setSelectedId(null);
      toast.success(t("scripts.deleted"));
    },
  });

  return (
    <PageShell maxWidth="full" className="flex flex-col h-[calc(100vh-64px)]">
      <PageHeader
        title={t("scripts.page_title")}
        subtitle={t("scripts.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("scripts.add")}
          </Button>
        }
      />

      <div className="grid grid-cols-[260px_1fr] gap-4 flex-1 min-h-0">
        <Card className="overflow-hidden h-fit max-h-full">
          <div className="p-2 border-b text-[11px] font-semibold text-muted-foreground">
            {t("scripts.list")}
          </div>
          {scripts.length === 0 ? (
            <p className="p-4 text-[12px] text-muted-foreground italic">{t("scripts.empty")}</p>
          ) : (
            <ul className="divide-y overflow-auto">
              {scripts.map((s) => (
                <li
                  key={s.id}
                  className={`px-3 py-2 flex items-center gap-2 cursor-pointer hover:bg-muted/40 ${selectedId === s.id ? "bg-muted" : ""}`}
                  onClick={() => setSelectedId(s.id)}
                >
                  <FileCode className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                  <span className="text-[12px] truncate flex-1">{s.name}</span>
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget({ id: s.id, name: s.name });
                    }}
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {selectedId ? (
          <ScriptEditor id={selectedId} summaries={scripts} t={t} />
        ) : (
          <Card className="p-8 text-center text-[12px] text-muted-foreground italic">
            {t("scripts.select_one")}
          </Card>
        )}
      </div>

      <CreateDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={(s) => {
          qc.invalidateQueries({ queryKey: ["scripts"] });
          setShowCreate(false);
          setSelectedId(s.id);
          toast.success(t("scripts.created"));
        }}
        t={t}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("scripts.delete_title")}
        description={t("scripts.delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />
    </PageShell>
  );
}

function ScriptEditor({ id, summaries, t }: {
  id: string;
  summaries: ScriptSummary[];
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["scripts", id],
    queryFn: () => scriptsApi.get(id),
  });
  const { data: namedTypes } = useInfraNamedTypes();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [executeOnTypeId, setExecuteOnTypeId] = useState<string>("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!detailQuery.data) return;
    setName(detailQuery.data.name);
    setDescription(detailQuery.data.description);
    setContent(detailQuery.data.content);
    setExecuteOnTypeId(detailQuery.data.execute_on_types_named ?? "");
    setDirty(false);
  }, [detailQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () => scriptsApi.update(id, {
      name: name.trim(),
      description,
      content,
      execute_on_types_named: executeOnTypeId || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      qc.invalidateQueries({ queryKey: ["scripts", id] });
      setDirty(false);
      toast.success(t("scripts.saved"));
    },
    onError: (e) => toast.error(String(e)),
  });

  if (detailQuery.isLoading) {
    return <Card className="p-6"><span className="text-[12px] text-muted-foreground">…</span></Card>;
  }

  return (
    <Card className="p-4 flex flex-col gap-3 min-h-0">
      <div className="grid grid-cols-[1fr_1fr_auto] gap-3 items-end">
        <div>
          <Label className="text-[11px]">{t("scripts.name")}</Label>
          <Input
            value={name}
            onChange={(e) => { setName(e.target.value); setDirty(true); }}
            className="mt-1 font-mono"
          />
        </div>
        <div>
          <Label className="text-[11px]">{t("scripts.execute_on_types_named")}</Label>
          <select
            value={executeOnTypeId}
            onChange={(e) => { setExecuteOnTypeId(e.target.value); setDirty(true); }}
            className={selectClass}
          >
            <option value="">— {t("common.none")} —</option>
            {(namedTypes ?? []).map((nt) => (
              <option key={nt.id} value={nt.id}>{nt.name}</option>
            ))}
          </select>
        </div>
        <Button
          disabled={!dirty || !name.trim() || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          <Save className="w-4 h-4" />
          {t("common.confirm")}
        </Button>
      </div>

      <div>
        <Label className="text-[11px]">{t("scripts.description")}</Label>
        <Input
          value={description}
          onChange={(e) => { setDescription(e.target.value); setDirty(true); }}
          className="mt-1"
          placeholder={t("scripts.description_placeholder")}
        />
      </div>

      <div className="flex flex-col flex-1 min-h-0">
        <Label className="text-[11px]">{t("scripts.content")}</Label>
        <ShellEditor
          value={content}
          onChange={(v) => { setContent(v); setDirty(true); }}
          className="mt-1 flex-1 min-h-0"
        />
        <p className="text-[10px] text-muted-foreground mt-1 shrink-0">
          {t("scripts.content_hint", { count: String(summaries.length) })}
        </p>
      </div>
    </Card>
  );
}

function CreateDialog({ open, onClose, onCreated, t }: {
  open: boolean;
  onClose: () => void;
  onCreated: (s: ScriptRow) => void;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) { setName(""); setDescription(""); setSaving(false); }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("scripts.add_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("scripts.name")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 font-mono" autoFocus />
          </div>
          <div>
            <Label className="text-[11px]">{t("scripts.description")}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                const created = await scriptsApi.create({
                  name: name.trim(),
                  description,
                  content: "#!/bin/bash\nset -euo pipefail\n",
                });
                onCreated(created);
              } catch (e) {
                toast.error(String(e));
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
