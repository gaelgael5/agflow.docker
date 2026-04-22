import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Box, ChevronDown, ChevronRight, Edit2, Eye, Layers, Lock, LockOpen, Play, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  projectsApi,
  groupsApi,
  instancesApi,
  deploymentsApi,
  type GroupSummary,
  type InstanceSummary,
  type DeploymentSummary,
} from "@/lib/projectsApi";
import { infraMachinesApi, type MachineSummary } from "@/lib/infraApi";
import {
  groupScriptsApi,
  scriptsApi,
  type GroupScript,
  type GroupScriptCreatePayload,
  type ScriptSummary,
  type ScriptTiming,
} from "@/lib/scriptsApi";
import { useVault } from "@/hooks/useVault";
import { VaultUnlockDialog } from "@/components/VaultUnlockDialog";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { productsApi, type ProductVariable, type ProductConnector, type ProductComputed, type ProductApiDef, type ProductService, type SharedDep } from "@/lib/productsApi";
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
  const vault = useVault();
  const { token } = useAuth();
  const isVaultOpen = vault.state === "unlocked";
  const [showVaultUnlock, setShowVaultUnlock] = useState(false);

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
  const [editGroup, setEditGroup] = useState<GroupSummary | null>(null);
  const [previewGroup, setPreviewGroup] = useState<GroupSummary | null>(null);
  const [showDeploy, setShowDeploy] = useState(false);
  const [deleteGroup, setDeleteGroup] = useState<GroupSummary | null>(null);
  const [deleteInstance, setDeleteInstance] = useState<InstanceSummary | null>(null);

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
          <div className="flex gap-2 items-center">
            <Button
              variant="ghost"
              size="icon"
              className={`h-8 w-8 ${isVaultOpen ? "text-green-500" : "text-orange-500"}`}
              title={isVaultOpen ? t("projects.vault_open") : t("projects.vault_locked")}
              onClick={() => {
                if (isVaultOpen) vault.lockVault();
                else setShowVaultUnlock(true);
              }}
            >
              {isVaultOpen ? <LockOpen className="w-4 h-4" /> : <Lock className="w-4 h-4" />}
            </Button>
            <Button variant="default" disabled={!isVaultOpen} onClick={() => setShowDeploy(true)}>
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

      {/* Edit group dialog */}
      <PromptDialog
        open={editGroup !== null}
        onOpenChange={(o) => { if (!o) setEditGroup(null); }}
        title={t("projects.group_edit_title")}
        fields={[
          { name: "name", label: t("projects.group_name"), required: true, defaultValue: editGroup?.name ?? "" },
          { name: "max_agents", label: t("projects.group_max_agents"), defaultValue: String(editGroup?.max_agents ?? 0) },
        ]}
        onSubmit={async (values) => {
          if (!editGroup) return;
          await groupsApi.update(editGroup.id, {
            name: values.name ?? editGroup.name,
            max_agents: parseInt(values.max_agents ?? "0", 10),
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

      {/* Vault unlock dialog */}
      <VaultUnlockDialog
        open={showVaultUnlock}
        email={(() => {
          try {
            const payload = JSON.parse(atob(token?.split(".")[1] ?? ""));
            return (payload.sub as string) ?? "";
          } catch { return ""; }
        })()}
        onComplete={() => setShowVaultUnlock(false)}
        onClose={() => setShowVaultUnlock(false)}
      />

      {/* Deploy dialog */}
      {showDeploy && (
        <DeployDialog
          projectId={projectId!}
          groups={groups}
          vault={vault}
          onClose={() => setShowDeploy(false)}
          t={t}
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

/* ── Deploy Dialog ────────────────────────────────────── */

function DeployDialog({ projectId, groups, vault: vaultCtx, onClose, t }: {
  projectId: string;
  groups: GroupSummary[];
  vault: ReturnType<typeof useVault>;
  onClose: () => void;
  t: (key: string) => string;
}) {
  const [servers, setServers] = useState<{ id: string; name: string; host: string; parent_id: string | null }[]>([]);
  const [groupServers, setGroupServers] = useState<Record<string, string>>({});
  const [deployment, setDeployment] = useState<DeploymentSummary | null>(null);
  const [generating, setGenerating] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [tab, setTab] = useState<"assign" | "compose" | "env">("assign");

  // Load child machines on open (service-category machines that can host deployments)
  useState(() => {
    infraMachinesApi.list().then((list) => {
      setServers(list.filter((m) => m.parent_id !== null).map((m) => ({
        id: m.id, name: m.name || m.host, host: m.host, parent_id: m.parent_id,
      })));
    });
  });

  const canGenerate = groups.every((g) => groupServers[g.id]);

  async function handleGenerate() {
    setGenerating(true);
    try {
      // Decrypt user secrets if vault is open
      const userSecrets: Record<string, string> = {};
      if (vaultCtx.state === "unlocked") {
        try {
          const { userSecretsApi } = await import("@/lib/userSecretsApi");
          const secrets = await userSecretsApi.list();
          for (const s of secrets) {
            try {
              userSecrets[s.name] = vaultCtx.decryptSecret(s.ciphertext, s.iv);
            } catch {
              // Can't decrypt — skip
            }
          }
        } catch {
          // No user secrets or vault error
        }
      }

      const dep = await deploymentsApi.create(projectId, groupServers);
      const generated = await deploymentsApi.generate(dep.id, userSecrets);
      setDeployment(generated);
      setTab("compose");
      toast.success(t("projects.deploy_generated"));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setGenerating(false);
    }
  }

  // Parse .env to know which secrets have values
  const resolvedEnvKeys = new Set<string>();
  const unresolvedEnvKeys = new Set<string>();
  if (deployment?.generated_env) {
    for (const line of deployment.generated_env.split("\n")) {
      const eqIdx = line.indexOf("=");
      if (eqIdx < 0) continue;
      const k = line.slice(0, eqIdx);
      const v = line.slice(eqIdx + 1);
      if (v) resolvedEnvKeys.add(k);
      else unresolvedEnvKeys.add(k);
    }
  }

  const nullableSet = new Set(deployment?.nullable_secrets ?? []);

  function colorizeYaml(text: string): React.ReactNode[] {
    const parts: React.ReactNode[] = [];
    const regex = /(\$\{[^}]+\})/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
      const token = match[1] ?? "";
      const ref = token.slice(2, -1);
      let color = "text-orange-400"; // unknown
      if (resolvedEnvKeys.has(ref)) color = "text-green-400";
      else if (unresolvedEnvKeys.has(ref)) color = nullableSet.has(ref) ? "text-yellow-400" : "text-red-400";
      parts.push(<span key={match.index} className={color}>{token}</span>);
      lastIndex = match.index + token.length;
    }
    if (lastIndex < text.length) parts.push(text.slice(lastIndex));
    return parts;
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-[75vw] max-h-[85vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("projects.deploy_title")}</DialogTitle>
        </DialogHeader>

        {/* Tabs */}
        <div className="flex gap-2 border-b pb-2">
          <Button size="sm" variant={tab === "assign" ? "default" : "outline"} onClick={() => setTab("assign")}>
            {t("projects.tab_assign")}
          </Button>
          {deployment && (
            <>
              <Button size="sm" variant={tab === "compose" ? "default" : "outline"} onClick={() => setTab("compose")}>
                docker-compose.yml
              </Button>
              <Button size="sm" variant={tab === "env" ? "default" : "outline"} onClick={() => setTab("env")}>
                .env
              </Button>
            </>
          )}
        </div>

        <div className="flex-1 overflow-auto">
          {tab === "assign" && (
            <div className="space-y-3 py-2">
              {groups.map((g) => (
                <div key={g.id} className="flex items-center gap-3">
                  <div className="w-48 shrink-0">
                    <span className="font-medium text-[13px]">{g.name}</span>
                    <span className="text-[10px] text-muted-foreground ml-2">({g.instance_count} inst.)</span>
                  </div>
                  <select
                    value={groupServers[g.id] ?? ""}
                    onChange={(e) => setGroupServers((prev) => ({ ...prev, [g.id]: e.target.value }))}
                    className="flex h-8 flex-1 rounded-md border border-input bg-background px-3 py-1 text-[12px] font-mono shadow-sm"
                  >
                    <option value="">— {t("projects.select_server")} —</option>
                    {servers.map((s) => (
                      <option key={s.id} value={s.id}>{s.name} ({s.host})</option>
                    ))}
                  </select>
                </div>
              ))}

              <div className="flex justify-end pt-3">
                <Button disabled={!canGenerate || generating} onClick={handleGenerate}>
                  {generating ? "..." : t("projects.deploy_generate")}
                </Button>
              </div>
            </div>
          )}

          {tab === "compose" && deployment?.generated_compose && (
            <pre className="p-4 bg-zinc-950 text-zinc-300 rounded-md text-[12px] font-mono whitespace-pre-wrap leading-5 overflow-auto max-h-[60vh]">
              {colorizeYaml(deployment.generated_compose)}
            </pre>
          )}

          {tab === "env" && deployment?.generated_env && (
            <pre className="p-4 bg-zinc-950 text-zinc-300 rounded-md text-[12px] font-mono whitespace-pre-wrap leading-5 overflow-auto max-h-[60vh]">
              {deployment.generated_env.split("\n").map((line, i) => {
                const [k, ...rest] = line.split("=");
                const v = rest.join("=");
                const isEmpty = !v;
                const isNullable = k ? nullableSet.has(k) : false;
                const valueClass = !isEmpty
                  ? "text-green-400"
                  : isNullable
                    ? "text-yellow-400"
                    : "text-red-400";
                return (
                  <div key={i}>
                    <span className="text-zinc-500">{k}</span>
                    <span className="text-zinc-600">=</span>
                    <span className={valueClass}>{v || "(empty)"}</span>
                  </div>
                );
              })}
            </pre>
          )}
        </div>

        {/* Footer with Push button */}
        {deployment && deployment.status === "generated" && (
          <div className="flex justify-end border-t pt-3">
            <Button
              disabled={pushing || [...unresolvedEnvKeys].some((k) => !nullableSet.has(k))}
              onClick={async () => {
                setPushing(true);
                try {
                  const res = await deploymentsApi.push(deployment.id);
                  const allOk = res.results.every((r) => r.success);
                  if (allOk) {
                    toast.success(t("projects.deploy_pushed"));
                    setDeployment({ ...deployment, status: "deployed" });
                  } else {
                    for (const r of res.results) {
                      if (!r.success) toast.error(`${r.server}: ${r.error || r.stderr}`);
                    }
                  }
                } catch (e) {
                  toast.error(String(e));
                } finally {
                  setPushing(false);
                }
              }}
            >
              <Play className="w-4 h-4" />
              {pushing ? "..." : t("projects.deploy_push")}
            </Button>
          </div>
        )}

        {deployment?.status === "deployed" && (
          <div className="flex items-center gap-2 border-t pt-3">
            <Badge variant="default" className="bg-green-600 text-white text-[10px]">
              {t("projects.deploy_deployed")}
            </Badge>
          </div>
        )}
      </DialogContent>
    </Dialog>
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

  useState(() => {
    groupsApi.preview(group.id)
      .then(setPreview)
      .catch((e) => toast.error(String(e)))
      .finally(() => setLoading(false));
  });

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

function VarRow({ v, values, onUpdate, t }: {
  v: ProductVariable;
  values: Record<string, string>;
  onUpdate: (name: string, val: string) => void;
  t: (key: string) => string;
}) {
  const isUndeclared = v.undeclared === true;
  return (
    <div className="flex items-start gap-3">
      <div className="w-48 shrink-0 pt-1.5">
        <div className="flex items-center gap-1.5">
          <Badge
            variant="outline"
            className={`text-[8px] font-mono ${
              isUndeclared ? "border-red-500 text-red-500" :
              v.type === "secret" ? "border-orange-400 text-orange-500" : "border-blue-400 text-blue-500"
            }`}
          >
            {v.syntax}
          </Badge>
          {v.required && <span className="text-destructive text-[10px]">*</span>}
          {isUndeclared && <span className="text-[9px] text-red-500">{t("projects.undeclared")}</span>}
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
        <Input
          value={values[v.name] ?? ""}
          onChange={(e) => onUpdate(v.name, e.target.value)}
          placeholder={v.default || v.name}
          className={`font-mono text-[12px] flex-1 h-8 ${v.type === "secret" ? "text-orange-500" : ""}`}
        />
      )}
    </div>
  );
}

/* ── Instance Row with expandable variables ───────────── */

import { Input } from "@/components/ui/input";
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
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

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
          const instSlug = instance.instance_name.toUpperCase().replace(/[^A-Z0-9]/g, "_");
          const merged = { ...instance.variables };
          for (const v of result.variables) {
            if (v.name in merged) continue;
            if (v.generate && v.generate !== "null") continue;
            if (v.default) {
              merged[v.name] = v.default;
            } else if (v.type === "secret") {
              merged[v.name] = "${" + instSlug + "_" + v.name + "}";
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

  async function save() {
    setSaving(true);
    try {
      await instancesApi.update(instance.id, { variables: values });
      qc.invalidateQueries({ queryKey: ["instances", projectId] });
      setDirty(false);
      toast.success(t("projects.variables_saved"));
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
                      <VarRow key={v.name} v={v} values={values} onUpdate={updateValue} t={t} />
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Secrets ${} */}
              {productVars.some((v) => v.type === "secret") && (
                <CollapsibleSection title={t("projects.section_secrets")} count={productVars.filter((v) => v.type === "secret").length}>
                  <div className="space-y-2">
                    {productVars.filter((v) => v.type === "secret").map((v) => (
                      <VarRow key={v.name} v={v} values={values} onUpdate={updateValue} t={t} />
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
                            {Object.entries(c.env).map(([k, v]) => (
                              <div key={k} className="flex items-center gap-2 text-[10px] font-mono">
                                <span className="text-muted-foreground">{k}</span>
                                <span className="text-muted-foreground">=</span>
                                <span className={v.startsWith("${") ? "text-orange-500" : "text-blue-500"}>{v}</span>
                              </div>
                            ))}
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
                        <div><span className="text-muted-foreground">auth:</span> {apiDef.auth_header} {apiDef.auth_prefix} <span className="text-orange-500">{apiDef.auth_secret_ref}</span></div>
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

function GroupScriptDialog({ open, initial, scripts, machines, onClose, onSubmit, t }: {
  open: boolean;
  initial: GroupScript | null;
  groupId: string;
  scripts: ScriptSummary[];
  machines: MachineSummary[];
  onClose: () => void;
  onSubmit: (p: GroupScriptCreatePayload, linkId?: string) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [scriptId, setScriptId] = useState("");
  const [machineId, setMachineId] = useState("");
  const [timing, setTiming] = useState<ScriptTiming>("before");
  const [position, setPosition] = useState("0");
  const [mappingText, setMappingText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setScriptId(initial.script_id);
      setMachineId(initial.machine_id);
      setTiming(initial.timing);
      setPosition(String(initial.position));
      setMappingText(Object.entries(initial.env_mapping).map(([k, v]) => `${k}=${v}`).join("\n"));
    } else {
      setScriptId(""); setMachineId(""); setTiming("before"); setPosition("0"); setMappingText("");
    }
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // When a script with an execute_on_types_named constraint is selected,
  // show only machines of that variant. Otherwise show all.
  const selectedScript = scripts.find((s) => s.id === scriptId);
  const requiredTypeId = selectedScript?.execute_on_types_named ?? null;
  const filteredMachines = requiredTypeId
    ? machines.filter((m) => m.type_id === requiredTypeId)
    : machines;

  // If the current machineId is no longer compatible with the new script, reset it.
  useEffect(() => {
    if (!machineId) return;
    if (!filteredMachines.some((m) => m.id === machineId)) setMachineId("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  const canSubmit = scriptId && machineId;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{initial ? t("scripts.group_edit_title") : t("scripts.group_add_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
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
          <div>
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
          <div>
            <Label className="text-[11px]">{t("scripts.group_env_mapping")}</Label>
            <textarea
              value={mappingText}
              onChange={(e) => setMappingText(e.target.value)}
              className="mt-1 flex w-full rounded-md border border-input bg-background px-3 py-2 text-[11px] font-mono"
              rows={3}
              placeholder="ip=MACHINE_IP&#10;user=SSH_USER"
            />
            <p className="text-[10px] text-muted-foreground mt-1">{t("scripts.group_env_mapping_hint")}</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!canSubmit || saving}
            onClick={async () => {
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
                  machine_id: machineId,
                  timing,
                  position: parseInt(position || "0", 10),
                  env_mapping: mapping,
                }, initial?.id);
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
