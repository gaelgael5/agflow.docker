import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Box, Layers, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  projectsApi,
  groupsApi,
  instancesApi,
  type GroupSummary,
  type InstanceSummary,
} from "@/lib/projectsApi";
import { api } from "@/lib/api";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-zinc-500 text-white",
  active: "bg-green-600 text-white",
  stopped: "bg-red-600 text-white",
};

interface ProductOption {
  id: string;
  display_name: string;
}

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const projectQuery = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });
  const groupsQuery = useQuery({
    queryKey: ["groups", projectId],
    queryFn: () => groupsApi.listByProject(projectId!),
    enabled: !!projectId,
  });
  const instancesQuery = useQuery({
    queryKey: ["instances", projectId],
    queryFn: () => instancesApi.listByProject(projectId!),
    enabled: !!projectId,
  });
  const productsQuery = useQuery({
    queryKey: ["product-catalog"],
    queryFn: async () => (await api.get<ProductOption[]>("/admin/products")).data,
  });

  const [showAddGroup, setShowAddGroup] = useState(false);
  const [addInstanceGroup, setAddInstanceGroup] = useState<GroupSummary | null>(null);
  const [deleteGroup, setDeleteGroup] = useState<GroupSummary | null>(null);
  const [deleteInstance, setDeleteInstance] = useState<InstanceSummary | null>(null);
  const [editVariables, setEditVariables] = useState<InstanceSummary | null>(null);

  const project = projectQuery.data;
  const groups = groupsQuery.data ?? [];
  const allInstances = instancesQuery.data ?? [];
  const products = productsQuery.data ?? [];

  function instancesForGroup(groupId: string) {
    return allInstances.filter((i) => i.group_id === groupId);
  }

  function productName(catalogId: string) {
    return products.find((p) => p.id === catalogId)?.display_name ?? catalogId;
  }

  if (!projectId) return null;

  return (
    <PageShell maxWidth="full">
      <PageHeader
        title={
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate("/projects")}>
              <ArrowLeft className="w-4 h-4" />
            </Button>
            <span>{project?.display_name ?? "..."}</span>
            {project && (
              <Badge className="text-[10px]">{project.environment}</Badge>
            )}
          </div>
        }
        subtitle={project?.description}
        actions={
          <Button onClick={() => setShowAddGroup(true)}>
            <Plus className="w-4 h-4" />
            {t("projects.add_group")}
          </Button>
        }
      />

      {groupsQuery.isLoading ? (
        <div className="space-y-3"><Skeleton className="h-32 w-full" /></div>
      ) : groups.length === 0 ? (
        <p className="text-muted-foreground italic">{t("projects.no_groups")}</p>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => {
            const instances = instancesForGroup(g.id);
            return (
              <Card key={g.id}>
                <div className="flex items-center justify-between px-4 py-3 bg-muted/40 border-b">
                  <div className="flex items-center gap-3">
                    <Layers className="w-5 h-5 text-muted-foreground" />
                    <div>
                      <span className="font-semibold">{g.name}</span>
                      <div className="flex items-center gap-2 mt-0.5">
                        <Badge variant="outline" className="text-[9px]">
                          <Bot className="w-3 h-3 mr-1" />
                          max {g.max_agents} agents
                        </Badge>
                        <span className="text-[11px] text-muted-foreground">
                          {instances.length} instance(s)
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button size="sm" variant="outline" onClick={() => setAddInstanceGroup(g)}>
                      <Plus className="w-3.5 h-3.5" />
                      {t("projects.add_instance")}
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7"
                      onClick={() => setDeleteGroup(g)}
                    >
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                    </Button>
                  </div>
                </div>

                <CardContent className="p-0">
                  {instances.length === 0 ? (
                    <p className="px-4 py-3 text-[12px] text-muted-foreground italic">
                      {t("projects.no_instances")}
                    </p>
                  ) : (
                    <div className="divide-y">
                      {instances.map((inst) => (
                        <div key={inst.id} className="flex items-center justify-between px-4 py-2">
                          <div className="flex items-center gap-3">
                            <Box className="w-4 h-4 text-muted-foreground" />
                            <div>
                              <span className="font-medium text-[13px]">{inst.instance_name}</span>
                              <div className="flex items-center gap-2 mt-0.5">
                                <Badge variant="secondary" className="text-[9px]">
                                  {productName(inst.catalog_id)}
                                </Badge>
                                <Badge variant="default" className={`text-[9px] ${STATUS_COLORS[inst.status] ?? ""}`}>
                                  {inst.status}
                                </Badge>
                                {Object.keys(inst.variables).length > 0 && (
                                  <span className="text-[10px] text-muted-foreground">
                                    {Object.keys(inst.variables).length} var(s)
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-1">
                            <Button variant="ghost" size="sm" className="h-7 text-[10px]"
                              onClick={() => setEditVariables(inst)}
                            >
                              {t("projects.edit_variables")}
                            </Button>
                            <Button variant="ghost" size="icon" className="h-7 w-7"
                              onClick={() => setDeleteInstance(inst)}
                            >
                              <Trash2 className="w-3 h-3 text-destructive" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Add group dialog */}
      <PromptDialog
        open={showAddGroup}
        onOpenChange={setShowAddGroup}
        title={t("projects.group_dialog_title")}
        fields={[
          { name: "name", label: t("projects.group_name"), required: true },
          { name: "max_agents", label: t("projects.group_max_agents"), defaultValue: "0" },
        ]}
        onSubmit={async (values) => {
          await groupsApi.create({
            project_id: projectId!,
            name: values.name ?? "",
            max_agents: parseInt(values.max_agents ?? "0", 10),
          });
          qc.invalidateQueries({ queryKey: ["groups", projectId] });
          setShowAddGroup(false);
          toast.success(t("projects.group_created"));
        }}
      />

      {/* Add instance dialog */}
      <PromptDialog
        open={addInstanceGroup !== null}
        onOpenChange={(o) => { if (!o) setAddInstanceGroup(null); }}
        title={t("projects.instance_dialog_title")}
        fields={[
          { name: "instance_name", label: t("projects.instance_name"), required: true },
          {
            name: "catalog_id",
            label: t("projects.instance_product"),
            required: true,
            options: products.map((p) => ({ value: p.id, label: p.display_name })),
          },
        ]}
        onSubmit={async (values) => {
          if (!addInstanceGroup) return;
          await instancesApi.create({
            group_id: addInstanceGroup.id,
            instance_name: values.instance_name ?? "",
            catalog_id: values.catalog_id ?? "",
          });
          qc.invalidateQueries({ queryKey: ["instances", projectId] });
          qc.invalidateQueries({ queryKey: ["groups", projectId] });
          setAddInstanceGroup(null);
          toast.success(t("projects.instance_created"));
        }}
      />

      {/* Delete group */}
      <ConfirmDialog
        open={deleteGroup !== null}
        onOpenChange={(o) => { if (!o) setDeleteGroup(null); }}
        title={t("projects.confirm_delete_group")}
        description={t("projects.confirm_delete_group_msg", { name: deleteGroup?.name ?? "" })}
        onConfirm={async () => {
          if (deleteGroup) {
            await groupsApi.remove(deleteGroup.id);
            qc.invalidateQueries({ queryKey: ["groups", projectId] });
            qc.invalidateQueries({ queryKey: ["instances", projectId] });
          }
        }}
      />

      {/* Delete instance */}
      <ConfirmDialog
        open={deleteInstance !== null}
        onOpenChange={(o) => { if (!o) setDeleteInstance(null); }}
        title={t("projects.confirm_delete_instance")}
        description={t("projects.confirm_delete_instance_msg", { name: deleteInstance?.instance_name ?? "" })}
        onConfirm={async () => {
          if (deleteInstance) {
            await instancesApi.remove(deleteInstance.id);
            qc.invalidateQueries({ queryKey: ["instances", projectId] });
            qc.invalidateQueries({ queryKey: ["groups", projectId] });
          }
        }}
      />

      {/* Edit variables dialog */}
      {editVariables && (
        <VariablesDialog
          instance={editVariables}
          onClose={() => setEditVariables(null)}
          onSave={async (vars) => {
            await instancesApi.update(editVariables.id, { variables: vars });
            qc.invalidateQueries({ queryKey: ["instances", projectId] });
            setEditVariables(null);
            toast.success(t("projects.variables_saved"));
          }}
          t={t}
        />
      )}
    </PageShell>
  );
}

/* ── Variables Editor Dialog ──────────────────────────── */

import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

function VariablesDialog({ instance, onClose, onSave, t }: {
  instance: InstanceSummary;
  onClose: () => void;
  onSave: (vars: Record<string, string>) => Promise<void>;
  t: (key: string) => string;
}) {
  const [entries, setEntries] = useState<{ key: string; value: string }[]>(() => {
    const vars = instance.variables ?? {};
    const list = Object.entries(vars).map(([key, value]) => ({ key, value }));
    if (list.length === 0) list.push({ key: "", value: "" });
    return list;
  });
  const [saving, setSaving] = useState(false);

  function updateEntry(index: number, field: "key" | "value", val: string) {
    setEntries((prev) => prev.map((e, i) => i === index ? { ...e, [field]: val } : e));
  }

  function addEntry() {
    setEntries((prev) => [...prev, { key: "", value: "" }]);
  }

  function removeEntry(index: number) {
    setEntries((prev) => prev.filter((_, i) => i !== index));
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("projects.variables_title")} — {instance.instance_name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2 max-h-[50vh] overflow-auto">
          {entries.map((e, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                value={e.key}
                onChange={(ev) => updateEntry(i, "key", ev.target.value)}
                placeholder="KEY"
                className="font-mono text-[12px] flex-1"
              />
              <span className="text-muted-foreground">=</span>
              <Input
                value={e.value}
                onChange={(ev) => updateEntry(i, "value", ev.target.value)}
                placeholder="value"
                className={`font-mono text-[12px] flex-1 ${e.value.startsWith("${") ? "text-orange-500" : ""}`}
              />
              <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => removeEntry(i)}>
                <Trash2 className="w-3 h-3 text-destructive" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addEntry}>
            <Plus className="w-3 h-3 mr-1" />
            {t("common.add")}
          </Button>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                const vars: Record<string, string> = {};
                for (const e of entries) {
                  if (e.key.trim()) vars[e.key.trim()] = e.value;
                }
                await onSave(vars);
              } finally {
                setSaving(false);
              }
            }}
          >
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
