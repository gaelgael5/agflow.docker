import { useEffect, useState, useMemo } from "react";
import { DeployWizardDialog } from "@/components/projects/DeployWizardDialog";
import { groupVariablesApi } from "@/lib/groupVariablesApi";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Box, ChevronDown, ChevronRight, ClipboardPaste, Copy, Edit2, Eye, FileText, Layers, Loader2, Play, Plus, RefreshCw, Save, Square, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  projectsApi,
  groupsApi,
  instancesApi,
  deploymentsApi,
  type GroupSummary,
  type InstanceSummary,
  type InstanceVariableStatus,
  type DeploymentSummary,
} from "@/lib/projectsApi";
import { infraMachinesApi, type MachineSummary } from "@/lib/infraApi";
import {
  groupScriptsApi,
  scriptsApi,
  type GroupScript,
  type GroupScriptCreatePayload,
  type InputStatus,
  type ScriptSummary,
  type ScriptTiming,
  type TargetKind,
  type TriggerOp,
  type TriggerRule,
} from "@/lib/scriptsApi";
import {
  runtimesApi,
  type ProjectGroupRuntime,
} from "@/lib/runtimesApi";
import { api } from "@/lib/api";
import { productsApi, type ProductVariable, type ProductConnector, type ProductComputed, type ProductApiDef, type ProductService, type SharedDep } from "@/lib/productsApi";
import { templatesApi } from "@/lib/templatesApi";
import { isMissing, getOrigin, extractRefs, parseEnvMachineRef, type VarSources } from "@/lib/missingVars";
import { useEnvMachineVarCheck } from "@/hooks/useEnvMachineVarCheck";
import { GroupVariablesSection } from "@/components/projects/GroupVariablesSection";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useProjectEnvVarsCheck } from "@/hooks/useInfraEnvVars";
import { useGroupAvailableVars } from "@/hooks/useGroupAvailableVars";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";

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

  // Filtre commun compose/swarm : templates ayant au moins un fichier `.docker.j2`.
  const templatesQuery = useQuery({
    queryKey: ["templates", "with-docker-j2"],
    queryFn: async () => {
      const summaries = await templatesApi.list();
      const details = await Promise.all(
        summaries.map((t) => templatesApi.get(t.slug).catch(() => null)),
      );
      return summaries.filter((_t, i) => {
        const d = details[i];
        return d?.files.some((f) => f.filename.endsWith(".docker.j2"));
      });
    },
  });
  const envVarsCheck = useProjectEnvVarsCheck(projectId);
  const dockerTemplateOptions = [
    { value: "", label: t("projects.group_compose_template_none") },
    ...(templatesQuery.data ?? []).map((tpl) => ({
      value: tpl.slug,
      label: tpl.display_name || tpl.slug,
    })),
  ];

  const [showAddGroup, setShowAddGroup] = useState(false);
  const [addInstanceGroup, setAddInstanceGroup] = useState<GroupSummary | null>(null);
  const [editGroup, setEditGroup] = useState<GroupSummary | null>(null);
  const [previewGroup, setPreviewGroup] = useState<GroupSummary | null>(null);
  const [wizardDep, setWizardDep] = useState<DeploymentSummary | null>(null);
  const [deleteGroup, setDeleteGroup] = useState<GroupSummary | null>(null);
  const [deleteInstance, setDeleteInstance] = useState<InstanceSummary | null>(null);

  const project = projectQuery.data;
  const groups = groupsQuery.data ?? [];
  const allInstances = instancesQuery.data ?? [];
  const products = productsQuery.data ?? [];

  const groupVarsQuery = useQuery({
    queryKey: ["group-vars-all", groups.map((g) => g.id)],
    queryFn: async () => {
      const results = await Promise.all(groups.map((g) => groupVariablesApi.list(g.id)));
      return results.flat();
    },
    enabled: groups.length > 0,
    staleTime: 30_000,
  });
  const groupVarsForWizard = useMemo(
    () => (groupVarsQuery.data ?? []).map((v) => ({ name: v.name, value: v.value ?? "" })),
    [groupVarsQuery.data],
  );

  const { data: beforeSteps = [] } = useQuery({
    queryKey: ["deployment-before-steps", wizardDep?.id],
    queryFn: () => deploymentsApi.getBeforeSteps(wizardDep!.id),
    enabled: !!wizardDep?.id && wizardDep.status !== "draft",
    staleTime: 30_000,
  });

  async function openWizard() {
    try {
      const dep = await deploymentsApi.create(projectId!, {});
      setWizardDep(dep);
    } catch (e) {
      toast.error(String(e));
    }
  }

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
          </div>
        }
        subtitle={project?.description}
        actions={
          <div className="flex gap-2 items-center">
            <Button variant="default" onClick={() => void openWizard()}>
              <Play className="w-4 h-4" />
              {t("projects.deploy")}
            </Button>
            <Button variant="outline" onClick={() => setShowAddGroup(true)}>
              <Plus className="w-4 h-4" />
              {t("projects.add_group")}
            </Button>
          </div>
        }
      />

      {envVarsCheck.data && envVarsCheck.data.total_missing > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
          <p className="font-medium text-destructive">
            {t("projects.env_vars_missing_banner", { count: envVarsCheck.data.total_missing })}
          </p>
          <ul className="mt-2 space-y-2">
            {envVarsCheck.data.items.map((item) => (
              <li key={item.group_script_id} className="text-xs">
                <div className="text-muted-foreground">
                  <span className="font-mono">{item.script_name}</span>
                  {" — "}
                  <span>{item.group_name}</span>
                </div>
                <ul className="ml-4 mt-0.5 space-y-0.5">
                  {item.missing.map((m) => (
                    <li key={m.var_name} className="text-muted-foreground">
                      <span className="font-mono">{m.var_name}</span>
                      {" : "}
                      <span>
                        {t(`projects.env_vars_reason.${m.kind}`, { detail: m.detail })}
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}

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
                    <Button variant="ghost" size="icon" className="h-7 w-7" title={t("projects.preview")} onClick={() => setPreviewGroup(g)}>
                      <Eye className="w-3.5 h-3.5 text-blue-500" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditGroup(g)}>
                      <Edit2 className="w-3.5 h-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7"
                      onClick={() => setDeleteGroup(g)}
                    >
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                    </Button>
                  </div>
                </div>

                <CardContent className="p-0">
                  <GroupVariablesSection groupId={g.id} />
                  {instances.length === 0 ? (
                    <p className="px-4 py-3 text-[12px] text-muted-foreground italic">
                      {t("projects.no_instances")}
                    </p>
                  ) : (
                    <div className="divide-y">
                      {instances.map((inst) => (
                        <InstanceRow
                          key={inst.id}
                          instance={inst}
                          productName={productName(inst.catalog_id)}
                          projectId={projectId!}
                          onDelete={() => setDeleteInstance(inst)}
                          qc={qc}
                          t={t}
                        />
                      ))}
                    </div>
                  )}
                  <GroupScriptsSection groupId={g.id} t={t} />
                  <GroupRuntimesSection groupId={g.id} t={t} />
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
          { name: "max_replicas", label: t("projects.group_max_replicas"), defaultValue: "1" },
          {
            name: "compose_template_slug",
            label: t("projects.group_compose_template"),
            options: dockerTemplateOptions,
            defaultValue: "",
          },
          {
            name: "swarm_template_slug",
            label: t("projects.group_swarm_template"),
            options: dockerTemplateOptions,
            defaultValue: "",
          },
        ]}
        onSubmit={async (values) => {
          await groupsApi.create({
            project_id: projectId!,
            name: values.name ?? "",
            max_agents: parseInt(values.max_agents ?? "0", 10),
            max_replicas: Math.max(1, parseInt(values.max_replicas ?? "1", 10)),
            compose_template_slug: values.compose_template_slug || null,
            swarm_template_slug: values.swarm_template_slug || null,
          });
          qc.invalidateQueries({ queryKey: ["groups", projectId] });
          setShowAddGroup(false);
          toast.success(t("projects.group_created"));
        }}
      />

      {/* Edit group dialog */}
      <PromptDialog
        open={editGroup !== null}
        onOpenChange={(o) => { if (!o) setEditGroup(null); }}
        title={t("projects.group_edit_title")}
        fields={[
          { name: "name", label: t("projects.group_name"), required: true, defaultValue: editGroup?.name ?? "" },
          { name: "max_agents", label: t("projects.group_max_agents"), defaultValue: String(editGroup?.max_agents ?? 0) },
          { name: "max_replicas", label: t("projects.group_max_replicas"), defaultValue: String(editGroup?.max_replicas ?? 1) },
          {
            name: "compose_template_slug",
            label: t("projects.group_compose_template"),
            options: dockerTemplateOptions,
            defaultValue: editGroup?.compose_template_slug ?? "",
          },
          {
            name: "swarm_template_slug",
            label: t("projects.group_swarm_template"),
            options: dockerTemplateOptions,
            defaultValue: editGroup?.swarm_template_slug ?? "",
          },
        ]}
        onSubmit={async (values) => {
          if (!editGroup) return;
          await groupsApi.update(editGroup.id, {
            name: values.name ?? editGroup.name,
            max_agents: parseInt(values.max_agents ?? "0", 10),
            max_replicas: Math.max(1, parseInt(values.max_replicas ?? "1", 10)),
            compose_template_slug: values.compose_template_slug || null,
            swarm_template_slug: values.swarm_template_slug || null,
          });
          qc.invalidateQueries({ queryKey: ["groups", projectId] });
          setEditGroup(null);
          toast.success(t("projects.group_updated"));
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

      {/* Deploy wizard */}
      {wizardDep !== null && (
        <DeployWizardDialog
          open
          onClose={() => setWizardDep(null)}
          deployment={wizardDep}
          groups={groups}
          groupVars={groupVarsForWizard}
          steps={beforeSteps}
          projectId={projectId!}
        />
      )}

      {/* Preview dialog */}
      {previewGroup && (
        <PreviewDialog
          group={previewGroup}
          onClose={() => setPreviewGroup(null)}
          t={t}
        />
      )}

    </PageShell>
  );
}

/* ── Preview Dialog ───────────────────────────────────── */

import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import type { GroupPreview } from "@/lib/projectsApi";

function PreviewDialog({ group, onClose, t }: {
  group: GroupSummary;
  onClose: () => void;
  t: (key: string) => string;
}) {
  const [preview, setPreview] = useState<GroupPreview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    groupsApi.preview(group.id)
      .then(setPreview)
      .catch((e) => toast.error(String(e)))
      .finally(() => setLoading(false));
  }, [group.id]);

  function colorize(yamlText: string, resolved: Set<string>, unresolved: Set<string>): React.ReactNode[] {
    // Split by ${...} and {{...}} patterns and colorize
    const parts: React.ReactNode[] = [];
    const regex = /(\$\{[^}]+\}|\{\{[^}]+\}\})/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(yamlText)) !== null) {
      if (match.index > lastIndex) {
        parts.push(yamlText.slice(lastIndex, match.index));
      }
      const token = match[1] ?? "";
      if (token.startsWith("${")) {
        const ref = token.slice(2, -1);
        if (resolved.has(ref)) {
          parts.push(<span key={match.index} className="text-green-400">{token}</span>);
        } else if (unresolved.has(ref)) {
          parts.push(<span key={match.index} className="text-red-400">{token}</span>);
        } else {
          parts.push(<span key={match.index} className="text-orange-400">{token}</span>);
        }
      } else {
        // {{ variable }}
        parts.push(<span key={match.index} className="text-cyan-400">{token}</span>);
      }
      lastIndex = match.index + token.length;
    }
    if (lastIndex < yamlText.length) {
      parts.push(yamlText.slice(lastIndex));
    }
    return parts;
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-[70vw] max-h-[80vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("projects.preview")} — {group.name}</DialogTitle>
        </DialogHeader>
        {loading ? (
          <p className="text-muted-foreground text-[12px] py-4">...</p>
        ) : preview ? (
          <div className="flex-1 overflow-auto">
            {preview.unresolved_secrets.length > 0 && (
              <div className="mb-2 flex items-center gap-2 flex-wrap">
                <span className="text-[10px] text-red-500">{t("projects.unresolved_secrets")}:</span>
                {preview.unresolved_secrets.map((s) => (
                  <Badge key={s} variant="outline" className="text-[8px] border-red-400 text-red-500 font-mono">${"{" + s + "}"}</Badge>
                ))}
              </div>
            )}
            <pre className="p-4 bg-zinc-950 text-zinc-300 rounded-md text-[12px] font-mono whitespace-pre-wrap leading-5 overflow-auto max-h-[60vh]">
              {colorize(
                preview.yaml,
                new Set(preview.resolved_secrets),
                new Set(preview.unresolved_secrets),
              )}
            </pre>
          </div>
        ) : (
          <p className="text-destructive">{t("projects.preview_error")}</p>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ── Collapsible Section ──────────────────────────────── */

function CollapsibleSection({ title, count, defaultOpen = true, children }: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 hover:text-foreground transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {title}
        {count !== undefined && <span className="text-[9px] font-normal">({count})</span>}
      </button>
      {open && children}
    </div>
  );
}

/* ── Variable Row ─────────────────────────────────────── */

function VarRow({ v, values, statuses, sources, onUpdate, onUpdateStatus, t }: {
  v: ProductVariable;
  values: Record<string, string>;
  statuses: Record<string, InstanceVariableStatus>;
  sources: VarSources;
  onUpdate: (name: string, val: string) => void;
  onUpdateStatus: (name: string, status: InstanceVariableStatus) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const isUndeclared = v.undeclared === true;
  const currentStatus = statuses[v.name] ?? "keep";
  const hasGenerator = Boolean(v.generate && v.generate !== "null");
  const hasValue = Boolean(String(values[v.name] ?? "").trim());
  const isResolved = !isUndeclared && (hasGenerator || hasValue);
  const displayedSyntax = v.syntax;
  const currentValue = values[v.name] ?? "";
  const missing = isMissing(v.name, currentValue, sources);
  const origin = getOrigin(v.name, currentValue, sources);
  const valueRefs = extractRefs(currentValue);
  const valueHasBrokenRef = valueRefs.length > 0 && valueRefs.some(
    (ref) => !sources.globalVarNames.has(ref) && !sources.groupVarNames.has(ref) && !sources.beforeOutputNames.has(ref),
  );
  const inputTextClass = valueHasBrokenRef ? "text-red-500" : "";
  // Undeclared + valeur fournie = vert (la valeur résout le problème)
  // Undeclared + aucune valeur = rouge (ni déclaré ni renseigné)
  const badgeColorClass = (isResolved || !missing || (isUndeclared && hasValue))
    ? "border-green-500 text-green-600"
    : (isUndeclared || v.required)
      ? "border-red-500 text-red-500"
      : "border-orange-400 text-orange-500";
  return (
    <div className="flex items-start gap-3">
      <div className="w-48 shrink-0 pt-1.5">
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className={`text-[8px] font-mono ${badgeColorClass}`}>
            {displayedSyntax}
          </Badge>
          {v.required && <span className="text-destructive text-[10px]">*</span>}
          {isUndeclared && (
            <span className={`text-[9px] ${missing ? "text-red-500" : "text-muted-foreground"}`}>
              {t("projects.undeclared")}
            </span>
          )}
        </div>
        {v.description && (
          <p className="text-[10px] text-muted-foreground mt-0.5">{v.description}</p>
        )}
      </div>
      {v.generate && v.generate !== "null" ? (
        <Input
          value={v.generate}
          readOnly
          className="font-mono text-[12px] flex-1 h-8 opacity-60 bg-muted"
        />
      ) : (
        <div className="flex items-start gap-1 flex-1">
          {window.location.protocol === "https:" && (
            <button
              type="button"
              title={t("projects.var_paste")}
              className="p-1 shrink-0 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors mt-0.5"
              onClick={async () => {
                const text = await navigator.clipboard.readText();
                onUpdate(v.name, text);
              }}
            >
              <ClipboardPaste className="w-3.5 h-3.5" />
            </button>
          )}
          <div className="flex-1">
            <Input
              value={values[v.name] ?? ""}
              onChange={(e) => onUpdate(v.name, e.target.value)}
              placeholder={v.default || v.name}
              className={`font-mono text-[12px] w-full h-8 ${inputTextClass}`}
            />
            {!missing && origin !== "missing" && (
              <p className="text-[9px] text-muted-foreground mt-0.5">
                {t(`projects.var_origin_${origin}`)}
              </p>
            )}
          </div>
        </div>
      )}
      <select
        value={currentStatus}
        onChange={(e) => onUpdateStatus(v.name, e.target.value as InstanceVariableStatus)}
        className="h-8 text-[11px] rounded-md border border-input bg-background px-2"
        title={t(`projects.var_status_${currentStatus}_tooltip`)}
      >
        <option value="keep">{t("projects.var_status_keep")}</option>
        <option value="clean">{t("projects.var_status_clean")}</option>
        <option value="replace">{t("projects.var_status_replace")}</option>
      </select>
    </div>
  );
}

/* ── Instance Row with expandable variables ───────────── */

import type { QueryClient } from "@tanstack/react-query";

function InstanceRow({ instance, productName: pName, projectId, onDelete, qc, t }: {
  instance: InstanceSummary;
  productName: string;
  projectId: string;
  onDelete: () => void;
  qc: QueryClient;
  t: (key: string) => string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [productVars, setProductVars] = useState<ProductVariable[] | null>(null);
  const [connectors, setConnectors] = useState<ProductConnector[]>([]);
  const [computed, setComputed] = useState<ProductComputed[]>([]);
  const [apiDef, setApiDef] = useState<ProductApiDef | null>(null);
  const [services, setServices] = useState<ProductService[]>([]);
  const [sharedDeps, setSharedDeps] = useState<SharedDep[]>([]);
  const [availableServices, setAvailableServices] = useState<import("@/lib/projectsApi").AvailableService[]>([]);
  const [values, setValues] = useState<Record<string, string>>(instance.variables ?? {});
  const [statuses, setStatuses] = useState<Record<string, InstanceVariableStatus>>(
    (instance.variable_statuses ?? {}) as Record<string, InstanceVariableStatus>,
  );
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const sources = useGroupAvailableVars(instance.group_id);

  function toggle() {
    if (!expanded && productVars === null) {
      productsApi.getVariables(instance.catalog_id)
        .then((result) => {
          setProductVars(result.variables);
          setConnectors(result.connectors);
          setComputed(result.computed);
          setApiDef(result.api);
          setServices(result.services);
          setSharedDeps(result.shared_deps);
          // Load available services if there are shared deps
          if (result.shared_deps.length > 0) {
            groupsApi.availableServices(instance.group_id)
              .then(setAvailableServices)
              .catch(() => setAvailableServices([]));
          }
          const merged = { ...instance.variables };
          for (const v of result.variables) {
            if (v.name in merged) continue;
            if (v.generate && v.generate !== "null") continue;
            if (v.default) {
              merged[v.name] = String(v.default);
            }
          }
          setValues(merged);
        })
        .catch(() => setProductVars([]));
    }
    setExpanded(!expanded);
  }

  function updateValue(name: string, val: string) {
    setValues((prev) => ({ ...prev, [name]: val }));
    setDirty(true);
  }

  function updateStatus(name: string, s: InstanceVariableStatus) {
    setStatuses((prev) => ({ ...prev, [name]: s }));
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    try {
      await instancesApi.update(instance.id, { variables: values, variable_statuses: statuses });
      qc.invalidateQueries({ queryKey: ["instances", projectId] });
      setDirty(false);
      toast.success(t("projects.variables_saved"));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-3">
          <button onClick={toggle} className="text-muted-foreground hover:text-foreground transition-colors">
            {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
          <Box className="w-4 h-4 text-muted-foreground" />
          <div>
            <span className="font-medium text-[13px]">{instance.instance_name}</span>
            <div className="flex items-center gap-2 mt-0.5">
              <Badge variant="secondary" className="text-[9px]">{pName}</Badge>
              <Badge variant="default" className={`text-[9px] ${STATUS_COLORS[instance.status] ?? ""}`}>
                {instance.status}
              </Badge>
              {Object.keys(instance.variables).length > 0 && (
                <span className="text-[10px] text-muted-foreground">
                  {Object.keys(instance.variables).length} var(s)
                </span>
              )}
            </div>
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onDelete}>
          <Trash2 className="w-3 h-3 text-destructive" />
        </Button>
      </div>

      {expanded && (
        <div className="px-12 pb-3 space-y-4">
          {productVars === null ? (
            <p className="text-[11px] text-muted-foreground">...</p>
          ) : productVars.length === 0 ? (
            <p className="text-[11px] text-muted-foreground italic">{t("projects.no_variables")}</p>
          ) : (
            <>
              {/* Sub-block: Variables {{ }} */}
              {productVars.some((v) => v.type === "variable") && (
                <CollapsibleSection title={t("projects.section_variables")} count={productVars.filter((v) => v.type === "variable").length}>
                  <div className="space-y-2">
                    {productVars.filter((v) => v.type === "variable").map((v) => (
                      <VarRow key={v.name} v={v} values={values} statuses={statuses} sources={sources} onUpdate={updateValue} onUpdateStatus={updateStatus} t={t} />
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Secrets ${} */}
              {productVars.some((v) => v.type === "secret") && (
                <CollapsibleSection title={t("projects.section_secrets")} count={productVars.filter((v) => v.type === "secret").length}>
                  <div className="space-y-2">
                    {productVars.filter((v) => v.type === "secret").map((v) => (
                      <VarRow key={v.name} v={v} values={values} statuses={statuses} sources={sources} onUpdate={updateValue} onUpdateStatus={updateStatus} t={t} />
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Shared dependencies */}
              {sharedDeps.length > 0 && (
                <CollapsibleSection title={t("projects.section_shared")} count={sharedDeps.length}>
                  <div className="space-y-2">
                    {sharedDeps.map((dep) => {
                      // Show services from other instances in the group
                      const otherServices = availableServices.filter((s) => s.instance_id !== instance.id);
                      return (
                        <div key={dep.name} className="flex items-start gap-3">
                          <div className="w-48 shrink-0 pt-1.5">
                            <Badge variant="outline" className="text-[8px] font-mono border-purple-400 text-purple-500">
                              {dep.syntax}
                            </Badge>
                          </div>
                          <select
                            value={values[`shared.${dep.name}`] ?? ""}
                            onChange={(e) => updateValue(`shared.${dep.name}`, e.target.value)}
                            className="flex h-8 flex-1 rounded-md border border-input bg-background px-3 py-1 text-[12px] font-mono shadow-sm"
                          >
                            <option value="">— {t("projects.select_service")} —</option>
                            {otherServices.map((s) => (
                              <option key={s.container_name} value={s.container_name}>
                                {s.container_name} ({s.image}{s.ports.length > 0 ? ` :${s.ports.join(",")}` : ""})
                              </option>
                            ))}
                          </select>
                        </div>
                      );
                    })}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Computed */}
              {computed.length > 0 && (
                <CollapsibleSection title={t("projects.section_computed")} count={computed.length} defaultOpen={false}>
                  <div className="space-y-1">
                    {computed.map((c) => (
                      <div key={c.path} className="flex items-center gap-3">
                        <Badge variant="outline" className="text-[8px] font-mono border-zinc-400 text-zinc-500">
                          {"{{ " + c.path + " }}"}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">{c.description}</span>
                      </div>
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Connectors */}
              {connectors.length > 0 && (
                <CollapsibleSection title={t("projects.section_connectors")} count={connectors.length} defaultOpen={false}>
                  <div className="space-y-2">
                    {connectors.map((c) => (
                      <div key={c.name} className="border rounded-md p-3 bg-muted/20">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium text-[12px]">{c.name}</span>
                          <Badge variant="outline" className="text-[8px]">{c.transport}</Badge>
                          <Badge variant="outline" className="text-[8px]">{c.runtime}</Badge>
                          {c.status && <Badge variant="secondary" className="text-[8px]">{c.status}</Badge>}
                        </div>
                        {c.description && <p className="text-[10px] text-muted-foreground mb-1.5">{c.description}</p>}
                        {c.package && <code className="text-[10px] font-mono text-muted-foreground">{c.package}</code>}
                        {Object.keys(c.env).length > 0 && (
                          <div className="mt-2 space-y-0.5">
                            {Object.entries(c.env).map(([k, v]) => {
                              return (
                                <div key={k} className="flex items-center gap-2 text-[10px] font-mono">
                                  <span className="text-muted-foreground">{k}</span>
                                  <span className="text-muted-foreground">=</span>
                                  <span className={v.startsWith("${") ? "text-orange-500" : "text-blue-500"}>{v}</span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: API */}
              {apiDef && (
                <CollapsibleSection title={t("projects.section_api")} defaultOpen={false}>
                  <div className="border rounded-md p-3 bg-muted/20 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[8px]">{apiDef.source}</Badge>
                    </div>
                    <div className="text-[10px] font-mono space-y-0.5">
                      <div><span className="text-muted-foreground">url:</span> <span className="text-blue-500">{apiDef.url}</span></div>
                      <div><span className="text-muted-foreground">base_url:</span> <span className="text-blue-500">{apiDef.base_url}</span></div>
                      {apiDef.auth_header && (
                        <div><span className="text-muted-foreground">auth:</span> {apiDef.auth_header} {apiDef.auth_prefix} <span className="text-orange-500">{apiDef.auth_secret_ref ?? ""}</span></div>
                      )}
                    </div>
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Services (exposed) */}
              {services.length > 0 && (
                <CollapsibleSection title={t("projects.section_services")} count={services.length} defaultOpen={false}>
                  <div className="space-y-2">
                    {services.map((svc) => (
                      <div key={svc.id} className="border rounded-md p-3 bg-muted/20">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium text-[12px]">{svc.id}</span>
                          {svc.ports.map((p) => (
                            <Badge key={p} variant="outline" className="text-[8px] font-mono">{p}</Badge>
                          ))}
                        </div>
                        <code className="text-[10px] font-mono text-muted-foreground">{svc.image}</code>
                        {svc.requires_services.length > 0 && (
                          <div className="flex items-center gap-1 mt-1">
                            <span className="text-[9px] text-muted-foreground">{t("projects.requires")}:</span>
                            {svc.requires_services.map((r) => (
                              <Badge key={r} variant="secondary" className="text-[8px]">{r}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {dirty && (
                <div className="flex justify-end pt-1">
                  <Button size="sm" disabled={saving} onClick={save}>
                    <Save className="w-3.5 h-3.5 mr-1" />
                    {saving ? "..." : t("projects.variables_save")}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Group runtimes section ──────────────────────────── */

function GroupRuntimesSection({ groupId, t }: {
  groupId: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const q = useQuery({
    queryKey: ["group-runtimes", groupId],
    queryFn: () => runtimesApi.listByGroup(groupId),
  });
  const runtimes = q.data ?? [];

  return (
    <div className="border-t px-4 py-3">
      <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2">
        {t("projects.runtimes_title", { count: String(runtimes.length) })}
      </h4>
      {runtimes.length === 0 ? (
        <p className="text-[11px] text-muted-foreground italic">{t("projects.runtimes_empty")}</p>
      ) : (
        <div className="space-y-1">
          {runtimes.map((r) => <RuntimeRow key={r.id} runtime={r} t={t} />)}
        </div>
      )}
    </div>
  );
}

function RuntimeRow({ runtime, t }: {
  runtime: ProjectGroupRuntime;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const [runtimeState, setRuntimeState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  async function handleDelete() {
    try {
      await runtimesApi.remove(runtime.id);
      qc.invalidateQueries({ queryKey: ["group-runtimes", runtime.group_id] });
      toast.success(t("projects.runtime_deleted"));
    } catch (e) {
      toast.error(String(e));
    }
  }

  async function refresh() {
    setLoading(true);
    try {
      const r = await runtimesApi.status(runtime.id);
      setRuntimeState(r.overall_state);
    } catch (e) {
      setRuntimeState("error");
      toast.error(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function doStart() {
    try { await runtimesApi.start(runtime.id); toast.success(t("projects.runtime_start_ok")); refresh(); }
    catch (e) { toast.error(String(e)); }
  }

  async function doStop() {
    try { await runtimesApi.stop(runtime.id); toast.success(t("projects.runtime_stop_ok")); refresh(); }
    catch (e) { toast.error(String(e)); }
  }

  const statusColor =
    runtime.status === "deployed" ? "bg-green-600 text-white"
    : runtime.status === "failed" ? "bg-red-600 text-white"
    : "bg-zinc-500 text-white";

  const runtimeBadgeColor =
    runtimeState === "running" ? "bg-green-600 text-white"
    : runtimeState === "stopped" ? "bg-zinc-600 text-white"
    : runtimeState === "partial" ? "bg-yellow-500 text-white"
    : runtimeState ? "bg-red-600 text-white"
    : "";

  return (
    <div className="border rounded p-2 bg-muted/20">
      <div className="flex items-center gap-2 text-[11px]">
        <Badge variant="outline" className="text-[9px] font-mono">#{runtime.seq}</Badge>
        <code className="font-mono text-[9px] text-muted-foreground" title={runtime.id}>{runtime.id.slice(0, 8)}…</code>
        <Badge variant="default" className={`text-[9px] ${statusColor}`}>{runtime.status}</Badge>
        {runtimeState && (
          <Badge variant="default" className={`text-[9px] ${runtimeBadgeColor}`}>{runtimeState}</Badge>
        )}
        <span className="text-muted-foreground">→ {runtime.machine_name}</span>
        {runtime.remote_path && (
          <code className="text-[10px] font-mono text-muted-foreground">{runtime.remote_path}</code>
        )}
        <div className="flex-1" />
        <Button variant="ghost" size="icon" className="h-6 w-6" title={t("projects.runtime_refresh")} onClick={refresh} disabled={loading}>
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
        </Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" title={t("projects.runtime_start")} onClick={doStart}>
          <Play className="w-3 h-3 text-green-600" />
        </Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" title={t("projects.runtime_stop")} onClick={doStop}>
          <Square className="w-3 h-3 text-orange-600" />
        </Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" title={t("projects.runtime_view")} onClick={() => setShowDetail(true)}>
          <FileText className="w-3 h-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-6 w-6" title={t("projects.runtime_delete")} onClick={() => setShowDelete(true)}>
          <Trash2 className="w-3 h-3 text-destructive" />
        </Button>
      </div>
      {runtime.error_message && (
        <p className="text-[10px] text-red-500 mt-1 font-mono">{runtime.error_message}</p>
      )}
      {showDetail && (
        <RuntimeDetailDialog runtimeId={runtime.id} onClose={() => setShowDetail(false)} t={t} />
      )}
      <ConfirmDialog
        open={showDelete}
        onOpenChange={(o) => { if (!o) setShowDelete(false); }}
        title={t("projects.runtime_delete_title", { seq: String(runtime.seq) })}
        description={
          runtimeState === "running" || runtimeState === "partial"
            ? t("projects.runtime_delete_running_message", { seq: String(runtime.seq) })
            : t("projects.runtime_delete_message", { seq: String(runtime.seq) })
        }
        onConfirm={handleDelete}
      />
    </div>
  );
}

function RuntimeDetailDialog({ runtimeId, onClose, t }: {
  runtimeId: string;
  onClose: () => void;
  t: (key: string) => string;
}) {
  const q = useQuery({
    queryKey: ["group-runtime", runtimeId],
    queryFn: () => runtimesApi.get(runtimeId),
  });
  const [tab, setTab] = useState<"compose" | "env">("compose");

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-[70vw] max-h-[80vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("projects.runtime_view")} — {q.data ? `#${q.data.seq}` : runtimeId.slice(0, 8) + "…"}</DialogTitle>
        </DialogHeader>
        <div className="flex gap-2 border-b pb-2">
          <Button size="sm" variant={tab === "compose" ? "default" : "outline"} onClick={() => setTab("compose")}>
            docker-compose.yml
          </Button>
          <Button size="sm" variant={tab === "env" ? "default" : "outline"} onClick={() => setTab("env")}>
            .env
          </Button>
        </div>
        <div className="flex-1 overflow-auto">
          {q.isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : q.isError ? (
            <p className="text-destructive text-[12px]">{String(q.error)}</p>
          ) : (
            <pre className="p-3 bg-zinc-950 text-zinc-200 rounded text-[11px] font-mono whitespace-pre-wrap leading-5 overflow-auto">
              {tab === "compose" ? (q.data?.compose_yaml || "(empty)") : (q.data?.env_text || "(empty)")}
            </pre>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Group → scripts section ─────────────────────────── */

function GroupScriptsSection({ groupId, t }: {
  groupId: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const linksQuery = useQuery({
    queryKey: ["group-scripts", groupId],
    queryFn: () => groupScriptsApi.list(groupId),
  });
  const scriptsQuery = useQuery({ queryKey: ["scripts"], queryFn: () => scriptsApi.list() });
  const machinesQuery = useQuery({ queryKey: ["infra-machines"], queryFn: () => infraMachinesApi.list() });

  const [editTarget, setEditTarget] = useState<GroupScript | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const links = linksQuery.data ?? [];
  const beforeLinks = links.filter((l) => l.timing === "before");
  const afterLinks = links.filter((l) => l.timing === "after");

  return (
    <div className="border-t px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
          {t("scripts.group_title")}
        </h4>
        <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => setShowAdd(true)}>
          <Plus className="w-3 h-3" />
          {t("scripts.group_add")}
        </Button>
      </div>

      {links.length === 0 ? (
        <p className="text-[11px] text-muted-foreground italic">{t("scripts.group_empty")}</p>
      ) : (
        <div className="space-y-1">
          {beforeLinks.length > 0 && (
            <div>
              <span className="text-[10px] text-muted-foreground">{t("scripts.group_timing_before")}</span>
              <ScriptLinkList links={beforeLinks} groupId={groupId} onEdit={setEditTarget} qc={qc} t={t} />
            </div>
          )}
          {afterLinks.length > 0 && (
            <div>
              <span className="text-[10px] text-muted-foreground">{t("scripts.group_timing_after")}</span>
              <ScriptLinkList links={afterLinks} groupId={groupId} onEdit={setEditTarget} qc={qc} t={t} />
            </div>
          )}
        </div>
      )}

      <GroupScriptDialog
        open={showAdd || editTarget !== null}
        initial={editTarget}
        groupId={groupId}
        scripts={scriptsQuery.data ?? []}
        machines={machinesQuery.data ?? []}
        onClose={() => { setShowAdd(false); setEditTarget(null); }}
        onSubmit={async (p, linkId) => {
          if (linkId) {
            await groupScriptsApi.update(groupId, linkId, p);
            toast.success(t("scripts.group_updated"));
          } else {
            await groupScriptsApi.create(groupId, p);
            toast.success(t("scripts.group_added"));
          }
          qc.invalidateQueries({ queryKey: ["group-scripts", groupId] });
          setShowAdd(false);
          setEditTarget(null);
        }}
        t={t}
      />
    </div>
  );
}

function ScriptLinkList({ links, groupId, onEdit, qc, t }: {
  links: GroupScript[];
  groupId: string;
  onEdit: (l: GroupScript) => void;
  qc: ReturnType<typeof useQueryClient>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  return (
    <ul className="divide-y border rounded mt-1">
      {links.map((l) => (
        <li key={l.id} className="px-3 py-1.5 flex items-center gap-2 text-[11px]">
          <Badge variant="outline" className="text-[9px] shrink-0">#{l.position}</Badge>
          <span className="font-mono truncate flex-1">{l.script_name}</span>
          <span className="text-muted-foreground shrink-0">{t("scripts.group_machine")}: {l.machine_name}</span>
          {Object.keys(l.env_mapping).length > 0 && (
            <Badge variant="secondary" className="text-[9px] shrink-0">
              {Object.keys(l.env_mapping).length} map
            </Badge>
          )}
          <Button variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={() => onEdit(l)}>
            <Edit2 className="w-3 h-3" />
          </Button>
          <Button
            variant="ghost" size="icon" className="h-5 w-5 shrink-0"
            onClick={async () => {
              try {
                await groupScriptsApi.remove(groupId, l.id);
                qc.invalidateQueries({ queryKey: ["group-scripts", groupId] });
                toast.success(t("scripts.group_removed"));
              } catch (e) {
                toast.error(String(e));
              }
            }}
          >
            <Trash2 className="w-3 h-3 text-destructive" />
          </Button>
        </li>
      ))}
    </ul>
  );
}

function GroupScriptDialog({ open, initial, groupId, scripts, machines, onClose, onSubmit, t }: {
  open: boolean;
  initial: GroupScript | null;
  groupId: string;
  scripts: ScriptSummary[];
  machines: MachineSummary[];
  onClose: () => void;
  onSubmit: (p: GroupScriptCreatePayload, linkId?: string) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const scriptPosition = initial?.position ?? 999;
  const sources = useGroupAvailableVars(groupId, scriptPosition);

  const [activeTab, setActiveTab] = useState("general");
  const [scriptId, setScriptId] = useState("");
  const [targetKind, setTargetKind] = useState<TargetKind>("fixed_machine");
  const [machineId, setMachineId] = useState("");
  const [timing, setTiming] = useState<ScriptTiming>("before");
  const [position, setPosition] = useState("0");
  const [mappingText, setMappingText] = useState("");
  const [inputValues, setInputValues] = useState<Record<string, string>>({});
  const [inputStatuses, setInputStatuses] = useState<Record<string, InputStatus>>({});
  const [triggerRules, setTriggerRules] = useState<TriggerRule[]>([]);
  const [saving, setSaving] = useState(false);
  const envMachineCheck = useEnvMachineVarCheck(inputValues, machines);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setScriptId(initial.script_id);
      setTargetKind(initial.target_kind ?? "fixed_machine");
      setMachineId(initial.machine_id ?? "");
      setTiming(initial.timing);
      setPosition(String(initial.position));
      setMappingText(Object.entries(initial.env_mapping).map(([k, v]) => `${k}=${v}`).join("\n"));
      setInputValues(initial.input_values ?? {});
      setInputStatuses((initial.input_statuses ?? {}) as Record<string, InputStatus>);
      setTriggerRules(initial.trigger_rules ?? []);
    } else {
      setScriptId(""); setTargetKind("fixed_machine"); setMachineId("");
      setTiming("before"); setPosition("0");
      setMappingText(""); setInputValues({}); setInputStatuses({}); setTriggerRules([]);
    }
    setActiveTab("general");
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const selectedScript = scripts.find((s) => s.id === scriptId);
  const requiredTypeId = selectedScript?.execute_on_types_named ?? null;
  const declaredInputs = selectedScript?.input_variables ?? [];
  const declaredOutputs = selectedScript?.output_variables ?? [];

  useEffect(() => {
    if (!selectedScript) return;
    setInputValues((prev) => {
      const next = { ...prev };
      for (const v of selectedScript.input_variables ?? []) {
        if (next[v.name] === undefined || next[v.name] === "") {
          next[v.name] = v.default ?? "";
        }
      }
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  const filteredMachines = useMemo(
    () => requiredTypeId ? machines.filter((m) => m.type_id === requiredTypeId) : machines,
    [requiredTypeId, machines],
  );

  useEffect(() => {
    if (!machineId) return;
    if (!filteredMachines.some((m) => m.id === machineId)) setMachineId("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  const canSubmit = scriptId && (targetKind === "deployment_host" || machineId);

  async function handleSubmit() {
    setSaving(true);
    try {
      const mapping: Record<string, string> = {};
      for (const raw of mappingText.split("\n")) {
        const line = raw.trim();
        if (!line) continue;
        const eq = line.indexOf("=");
        if (eq < 0) continue;
        const k = line.slice(0, eq).trim();
        const v = line.slice(eq + 1).trim();
        if (k && v) mapping[k] = v;
      }
      await onSubmit({
        script_id: scriptId,
        target_kind: targetKind,
        machine_id: targetKind === "deployment_host" ? null : machineId,
        timing,
        position: parseInt(position || "0", 10),
        env_mapping: mapping,
        input_values: inputValues,
        input_statuses: inputStatuses,
        trigger_rules: triggerRules.filter((r) => r.variable.trim()),
      }, initial?.id);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-[900px] h-[790px] flex flex-col" aria-describedby={undefined}>
        <DialogHeader className="shrink-0">
          <DialogTitle>{initial ? t("scripts.group_edit_title") : t("scripts.group_add_title")}</DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
          <TabsList className="shrink-0 w-full justify-start">
            <TabsTrigger value="general">{t("scripts.group_tab_general")}</TabsTrigger>
            <TabsTrigger value="inputs">
              {t("scripts.group_tab_inputs")}
              {declaredInputs.length > 0 && (
                <span className="ml-1 text-[10px] text-muted-foreground">({declaredInputs.length})</span>
              )}
            </TabsTrigger>
            <TabsTrigger value="outputs">
              {t("scripts.group_tab_outputs")}
              {declaredOutputs.length > 0 && (
                <span className="ml-1 text-[10px] text-muted-foreground">({declaredOutputs.length})</span>
              )}
            </TabsTrigger>
            <TabsTrigger value="rules">
              {t("scripts.group_tab_rules")}
              {triggerRules.length > 0 && (
                <span className="ml-1 text-[10px] text-muted-foreground">({triggerRules.length})</span>
              )}
            </TabsTrigger>
          </TabsList>

          {/* ── Onglet 1 : Général ── */}
          <TabsContent value="general" className="flex-1 overflow-y-auto mt-0 pt-3 space-y-3">
            <div>
              <Label className="text-[11px]">{t("scripts.group_script")}</Label>
              <select value={scriptId} onChange={(e) => setScriptId(e.target.value)}
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm">
                <option value="">—</option>
                {scripts.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                    {s.execute_on_types_named_name ? ` [${s.execute_on_types_named_name}]` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[11px]">{t("scripts.group_target_kind")}</Label>
              <select value={targetKind} onChange={(e) => setTargetKind(e.target.value as TargetKind)}
                className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm">
                <option value="fixed_machine">{t("scripts.group_target_kind_fixed")}</option>
                <option value="deployment_host">{t("scripts.group_target_kind_deployment_host")}</option>
              </select>
            </div>
            {targetKind === "fixed_machine" ? (
              <div>
                <Label className="text-[11px]">{t("scripts.group_machine")}</Label>
                <select value={machineId} onChange={(e) => setMachineId(e.target.value)}
                  className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm">
                  <option value="">—</option>
                  {filteredMachines.map((m) => (
                    <option key={m.id} value={m.id}>{m.name || m.host}</option>
                  ))}
                </select>
                {requiredTypeId && filteredMachines.length === 0 && (
                  <p className="text-[10px] text-orange-600 mt-1">{t("scripts.group_no_matching_machine")}</p>
                )}
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground italic">
                {t("scripts.group_target_kind_deployment_host_hint")}
              </p>
            )}
            <div className="flex gap-4">
              <div className="flex-1">
                <Label className="text-[11px]">{t("scripts.group_timing")}</Label>
                <select value={timing} onChange={(e) => setTiming(e.target.value as ScriptTiming)}
                  className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm">
                  <option value="before">{t("scripts.group_timing_before")}</option>
                  <option value="after">{t("scripts.group_timing_after")}</option>
                </select>
              </div>
              <div>
                <Label className="text-[11px]">{t("scripts.group_position")}</Label>
                <Input type="number" value={position} onChange={(e) => setPosition(e.target.value)} className="mt-1 w-24 font-mono" />
              </div>
            </div>
            <div>
              <Label className="text-[11px]">{t("scripts.group_env_mapping")}</Label>
              <textarea
                value={mappingText}
                onChange={(e) => setMappingText(e.target.value)}
                className="mt-1 flex w-full rounded-md border border-input bg-background px-3 py-2 text-[11px] font-mono"
                rows={4}
                placeholder="ip=MACHINE_IP&#10;user=SSH_USER"
              />
              <p className="text-[10px] text-muted-foreground mt-1">{t("scripts.group_env_mapping_hint")}</p>
            </div>
          </TabsContent>

          {/* ── Onglet 2 : Variables d'entrée ── */}
          <TabsContent value="inputs" className="flex-1 overflow-y-auto mt-0 pt-3">
            {declaredInputs.length === 0 ? (
              <p className="text-[12px] text-muted-foreground italic">{t("scripts.group_no_inputs")}</p>
            ) : (
              <div className="space-y-3">
                {declaredInputs.map((iv) => {
                  const s = inputStatuses[iv.name] ?? "keep";
                  const val = inputValues[iv.name] ?? "";
                  const envRef = parseEnvMachineRef(val);
                  const isEnvMachineRef = envRef !== null && envRef.machine !== "<machine>";
                  const isEnvMachinePlaceholder = envRef !== null && envRef.machine === "<machine>";
                  const envMachineStatus = isEnvMachineRef
                    ? (envMachineCheck.get(`${envRef.machine}:${envRef.varName}`) ?? null)
                    : null;
                  const effectiveMissing = isEnvMachineRef
                    ? (envMachineStatus !== null && envMachineStatus !== "ok")
                    : !isEnvMachinePlaceholder && isMissing(iv.name, val, sources);
                  const origin = isEnvMachineRef && envMachineStatus === "ok"
                    ? "env_machine"
                    : isEnvMachinePlaceholder
                      ? "env_machine"
                      : getOrigin(iv.name, val, sources);
                  return (
                    <div key={iv.name}>
                      <Label className={`text-[10px] ${effectiveMissing ? "text-red-500" : ""}`}>
                        <span className="font-mono">{iv.name}</span>
                        {iv.description && <span className="text-muted-foreground ml-1">— {iv.description}</span>}
                      </Label>
                      <div className="flex gap-1 mt-1">
                        <div className="flex-1 flex flex-col">
                          <Input
                            value={val}
                            onChange={(e) => setInputValues({ ...inputValues, [iv.name]: e.target.value })}
                            className={`font-mono text-[11px] ${effectiveMissing ? "border-red-500 focus-visible:ring-red-500" : ""}`}
                            placeholder={iv.default || "${ENV_VAR} ou valeur littérale"}
                          />
                          {!effectiveMissing && origin !== "missing" && (
                            <p className="text-[9px] text-muted-foreground mt-0.5">
                              {t(`projects.var_origin_${origin}`)}
                            </p>
                          )}
                        </div>
                        <select
                          value={s}
                          onChange={(e) => setInputStatuses({ ...inputStatuses, [iv.name]: e.target.value as InputStatus })}
                          className="h-9 text-[11px] rounded-md border border-input bg-background px-2"
                          title={t(`scripts.inputs_status_${s}_tooltip`)}
                        >
                          <option value="keep">{t("scripts.inputs_status_keep")}</option>
                          <option value="clean">{t("scripts.inputs_status_clean")}</option>
                          <option value="replace">{t("scripts.inputs_status_replace")}</option>
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </TabsContent>

          {/* ── Onglet 3 : Variables de sortie ── */}
          <TabsContent value="outputs" className="flex-1 overflow-y-auto mt-0 pt-3">
            {declaredOutputs.length === 0 ? (
              <p className="text-[12px] text-muted-foreground italic">{t("scripts.group_no_outputs")}</p>
            ) : (
              <div className="space-y-2">
                {declaredOutputs.map((ov) => (
                  <div key={ov.name} className="flex items-start gap-2 rounded-md border px-3 py-2 bg-muted/30">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[12px] font-medium">{ov.name}</span>
                        {ov.via_env && (
                          <Badge variant="outline" className="text-[9px] h-4 px-1">env</Badge>
                        )}
                        {ov.path && (
                          <span className="text-[10px] text-muted-foreground font-mono">{ov.path}</span>
                        )}
                      </div>
                      {ov.description && (
                        <p className="text-[10px] text-muted-foreground mt-0.5">{ov.description}</p>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 shrink-0"
                      title={t("scripts.copy_var_ref")}
                      onClick={(e) => {
                        const text = `\${${ov.name}}`;
                        const copyViaExecCommand = () => {
                          // Insérer dans le dialog (pas body) pour rester dans le focus trap Radix
                          const container = (e.currentTarget as HTMLElement).closest('[role="dialog"]') ?? document.body;
                          const el = document.createElement("textarea");
                          el.value = text;
                          el.setAttribute("readonly", "");
                          el.style.cssText = "position:absolute;top:0;left:0;width:1px;height:1px;opacity:0;overflow:hidden";
                          container.appendChild(el);
                          el.focus();
                          el.select();
                          document.execCommand("copy");
                          el.remove();
                          toast.success(t("scripts.copy_var_ref_done", { name: ov.name }));
                        };
                        if (navigator.clipboard) {
                          navigator.clipboard.writeText(text)
                            .then(() => toast.success(t("scripts.copy_var_ref_done", { name: ov.name })))
                            .catch(copyViaExecCommand);
                        } else {
                          copyViaExecCommand();
                        }
                      }}
                    >
                      <Copy className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>

          {/* ── Onglet 4 : Règles de déclenchement ── */}
          <TabsContent value="rules" className="flex-1 overflow-y-auto mt-0 pt-3">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[11px] text-muted-foreground">{t("scripts.group_rules_hint")}</p>
              <Button
                type="button" size="sm" variant="outline" className="h-7 text-[11px] shrink-0"
                onClick={() => setTriggerRules([...triggerRules, { variable: "", op: "equals", value: "" }])}
              >
                <Plus className="w-3 h-3 mr-1" />
                {t("scripts.group_rules_add")}
              </Button>
            </div>
            {triggerRules.length === 0 ? (
              <p className="text-[12px] text-muted-foreground italic">{t("scripts.group_no_rules")}</p>
            ) : (
              <div className="space-y-1">
                {triggerRules.map((r, idx) => (
                  <div key={idx} className="grid grid-cols-[1fr_auto_1fr_auto] gap-1 items-center">
                    <Input
                      value={r.variable}
                      onChange={(e) => {
                        const next = [...triggerRules];
                        next[idx] = { ...next[idx]!, variable: e.target.value };
                        setTriggerRules(next);
                      }}
                      className="h-7 font-mono text-[11px]"
                      placeholder="VAR_NAME"
                    />
                    <select
                      value={r.op}
                      onChange={(e) => {
                        const next = [...triggerRules];
                        next[idx] = { ...next[idx]!, op: e.target.value as TriggerOp };
                        setTriggerRules(next);
                      }}
                      className="h-7 text-[11px] rounded-md border border-input bg-background px-2"
                    >
                      <option value="equals">{t("scripts.rule_op_equals")}</option>
                      <option value="not_equals">{t("scripts.rule_op_not_equals")}</option>
                      <option value="is_null">{t("scripts.rule_op_is_null")}</option>
                    </select>
                    <Input
                      value={r.value}
                      onChange={(e) => {
                        const next = [...triggerRules];
                        next[idx] = { ...next[idx]!, value: e.target.value };
                        setTriggerRules(next);
                      }}
                      className="h-7 text-[11px]"
                      placeholder="valeur"
                      disabled={r.op === "is_null"}
                    />
                    <Button
                      type="button" variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => setTriggerRules(triggerRules.filter((_, i) => i !== idx))}
                    >
                      <Trash2 className="w-3 h-3 text-destructive" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter className="shrink-0">
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button disabled={!canSubmit || saving} onClick={handleSubmit}>
            {saving ? "..." : t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
