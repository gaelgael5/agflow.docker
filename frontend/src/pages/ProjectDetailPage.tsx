import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Box, ChevronDown, ChevronRight, Edit2, Eye, FileText, Layers, Loader2, Lock, LockOpen, Play, Plus, RefreshCw, Save, Square, Trash2 } from "lucide-react";
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
  type TriggerOp,
  type TriggerRule,
} from "@/lib/scriptsApi";
import {
  runtimesApi,
  type ProjectGroupRuntime,
} from "@/lib/runtimesApi";
import { useVault } from "@/hooks/useVault";
import { VaultUnlockDialog } from "@/components/VaultUnlockDialog";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { productsApi, type ProductVariable, type ProductConnector, type ProductComputed, type ProductApiDef, type ProductService, type SharedDep } from "@/lib/productsApi";
import { templatesApi } from "@/lib/templatesApi";
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

  const templatesQuery = useQuery({
    queryKey: ["templates", "with-sh-j2"],
    queryFn: async () => {
      const summaries = await templatesApi.list();
      const details = await Promise.all(
        summaries.map((t) => templatesApi.get(t.slug).catch(() => null)),
      );
      return summaries.filter((_t, i) => {
        const d = details[i];
        return d?.files.some((f) => f.filename.endsWith(".sh.j2"));
      });
    },
  });
  const composeTemplateOptions = [
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
          {
            name: "compose_template_slug",
            label: t("projects.group_compose_template"),
            options: composeTemplateOptions,
            defaultValue: "",
          },
        ]}
        onSubmit={async (values) => {
          await groupsApi.create({
            project_id: projectId!,
            name: values.name ?? "",
            max_agents: parseInt(values.max_agents ?? "0", 10),
            compose_template_slug: values.compose_template_slug || null,
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
          {
            name: "compose_template_slug",
            label: t("projects.group_compose_template"),
            options: composeTemplateOptions,
            defaultValue: editGroup?.compose_template_slug ?? "",
          },
        ]}
        onSubmit={async (values) => {
          if (!editGroup) return;
          await groupsApi.update(editGroup.id, {
            name: values.name ?? editGroup.name,
            max_agents: parseInt(values.max_agents ?? "0", 10),
            compose_template_slug: values.compose_template_slug || null,
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
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [servers, setServers] = useState<{ id: string; name: string; host: string; parent_id: string | null }[]>([]);
  const [groupServers, setGroupServers] = useState<Record<string, string>>({});
  const [deployment, setDeployment] = useState<DeploymentSummary | null>(null);
  const [generating, setGenerating] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [tab, setTab] = useState<string>("assign");
  const composeTabPrefix = "compose-";
  const activeComposeGroupId = tab.startsWith(composeTabPrefix) ? tab.slice(composeTabPrefix.length) : null;

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
      setTab("data");
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

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-[75vw] h-[85vh] flex flex-col" aria-describedby={undefined}>
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
              <Button size="sm" variant={tab === "data" ? "default" : "outline"} onClick={() => setTab("data")}>
                {t("projects.tab_data")}
              </Button>
              <Button size="sm" variant={tab === "env" ? "default" : "outline"} onClick={() => setTab("env")}>
                .env
              </Button>
              <Button size="sm" variant={tab === "scripts" ? "default" : "outline"} onClick={() => setTab("scripts")}>
                {t("scripts.deploy_tab_title")}
              </Button>
              {groups
                .filter((g) => g.compose_template_slug)
                .map((g) => {
                  const tabKey = `${composeTabPrefix}${g.id}`;
                  return (
                    <Button
                      key={tabKey}
                      size="sm"
                      variant={tab === tabKey ? "default" : "outline"}
                      onClick={() => setTab(tabKey)}
                    >
                      {t("projects.tab_compose_group", { name: g.name })}
                    </Button>
                  );
                })}
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
            </div>
          )}

          {tab === "data" && deployment && (
            <DeployDataPanel deployment={deployment} t={t} />
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

          {tab === "scripts" && deployment && (
            <DeployScriptsPanel
              groupIds={groups.map((g) => g.id)}
              envText={deployment.generated_env ?? ""}
              t={t}
            />
          )}

          {activeComposeGroupId && deployment && (
            <GroupComposePanel
              deploymentId={deployment.id}
              groupId={activeComposeGroupId}
              t={t}
            />
          )}
        </div>

        {/* Footer : bouton Générer toujours dispo, Pousser quand le déploiement est prêt */}
        {deployment?.status !== "deployed" && (
          <div className="flex justify-end gap-2 border-t pt-3">
            <Button
              variant="outline"
              disabled={!canGenerate || generating}
              onClick={handleGenerate}
            >
              {generating ? "..." : t("projects.deploy_generate")}
            </Button>
            {deployment && deployment.status === "generated" && (
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
            )}
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

/* ── Deploy : vue Docker Compose rendu par groupe ───── */

function GroupComposePanel({ deploymentId, groupId, t }: {
  deploymentId: string;
  groupId: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["deployment-compose", deploymentId, groupId],
    queryFn: () => deploymentsApi.groupCompose(deploymentId, groupId),
    retry: false,
  });

  if (isLoading) {
    return <p className="text-[12px] text-muted-foreground italic p-4">{t("common.refresh")}…</p>;
  }
  if (error) {
    const axiosErr = error as { response?: { data?: { detail?: string } }; message?: string };
    const detail = axiosErr.response?.data?.detail ?? axiosErr.message ?? String(error);
    return (
      <pre className="text-[12px] text-red-400 p-4 whitespace-pre-wrap font-mono">
        {detail}
      </pre>
    );
  }
  return (
    <pre className="p-4 bg-zinc-950 text-zinc-300 rounded-md text-[12px] font-mono whitespace-pre leading-5 overflow-auto max-h-[60vh]">
      {data?.compose ?? ""}
    </pre>
  );
}


/* ── Deploy : vue Données (structure pré-résolue) ─────── */

function DeployDataPanel({ deployment, t }: {
  deployment: DeploymentSummary;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const data = deployment.generated_data as DeploymentData | Record<string, never>;
  const envMap: Record<string, string> = {};
  for (const line of (deployment.generated_env ?? "").split("\n")) {
    const s = line.trim();
    if (!s || s.startsWith("#") || !line.includes("=")) continue;
    const [k, ...rest] = line.split("=");
    if (k) envMap[k.trim()] = rest.join("=").trim();
  }
  const nullableSet = new Set(deployment.nullable_secrets ?? []);

  function refClass(name: string): string {
    const v = envMap[name];
    if (v) return "text-emerald-400";
    if (nullableSet.has(name)) return "text-amber-400";
    return "text-red-400";
  }

  function colorize(value: string): React.ReactNode[] {
    const parts: React.ReactNode[] = [];
    // Match both ${VAR} (env ref) and {{VAR}} (system placeholder resolved by renderer)
    const re = /(\$\{([A-Z_][A-Z0-9_]*)\})|(\{\{([A-Z_][A-Z0-9_]*)\}\})/g;
    let last = 0;
    let match;
    while ((match = re.exec(value)) !== null) {
      if (match.index > last) parts.push(value.slice(last, match.index));
      const isEnvRef = Boolean(match[1]);
      const name = isEnvRef ? match[2]! : match[4]!;
      const cls = isEnvRef ? refClass(name) : "text-sky-400";
      parts.push(
        <span key={match.index} className={cls}>
          {match[0]}
        </span>,
      );
      last = match.index + match[0].length;
    }
    if (last < value.length) parts.push(value.slice(last));
    return parts;
  }

  if (!("groups" in data) || !data.groups) {
    return (
      <p className="text-[12px] text-muted-foreground italic p-4">
        {t("projects.deploy_data_empty")}
      </p>
    );
  }

  return (
    <pre className="p-4 bg-zinc-950 text-zinc-300 rounded-md text-[12px] font-mono whitespace-pre leading-5 overflow-auto max-h-[60vh]">
      <span className="text-zinc-500"># project: </span>
      <span>{data.project.name}</span>
      <span className="text-zinc-500">  network: </span>
      <span className="text-sky-400">{data.project.network}</span>
      {"\n"}
      {data.groups.map((g) => (
        <div key={g.group.id}>
          {"\n"}
          <span className="text-sky-300"># group: {g.group.name}</span>
          <span className="text-zinc-500"> (slug={g.group_slug})</span>
          {"\n"}
          {g.instances.map((inst) => (
            <div key={inst.id}>
              <span className="text-zinc-500">  # instance: </span>
              <span className="text-fuchsia-300">{inst.instance_name}</span>
              <span className="text-zinc-500">  ({inst.catalog_id})</span>
              {"\n"}
              {inst.services.map((svc) => (
                <div key={svc.container_name}>
                  <span className="text-amber-300">  {svc.container_name}:</span>
                  {"\n"}
                  <span className="text-zinc-500">    image: </span>
                  {svc.image}{"\n"}
                  <span className="text-zinc-500">    restart: </span>
                  {svc.restart}{"\n"}
                  <span className="text-zinc-500">    networks: </span>
                  [{svc.networks.join(", ")}]{"\n"}
                  {svc.ports.length > 0 && (
                    <>
                      <span className="text-zinc-500">    ports: </span>
                      [{svc.ports.join(", ")}]{"\n"}
                    </>
                  )}
                  <span className="text-zinc-500">    labels:</span>{"\n"}
                  {svc.labels.map((lbl, i) => (
                    <div key={i}>
                      <span className="text-zinc-500">      - </span>
                      {colorize(lbl)}{"\n"}
                    </div>
                  ))}
                  {Object.keys(svc.environment).length > 0 && (
                    <>
                      <span className="text-zinc-500">    environment:</span>{"\n"}
                      {Object.entries(svc.environment).map(([k, v]) => (
                        <div key={k}>
                          <span className="text-zinc-500">      {k}: </span>
                          <span>&quot;{colorize(v)}&quot;</span>{"\n"}
                        </div>
                      ))}
                    </>
                  )}
                  {svc.volumes.length > 0 && (
                    <>
                      <span className="text-zinc-500">    volumes:</span>{"\n"}
                      {svc.volumes.map((vol, i) => (
                        <div key={i}>
                          <span className="text-zinc-500">      - </span>
                          {vol.docker_volume || "(empty)"}:{vol.mount}{"\n"}
                        </div>
                      ))}
                    </>
                  )}
                  {svc.depends_on.length > 0 && (
                    <>
                      <span className="text-zinc-500">    depends_on:</span>{"\n"}
                      {svc.depends_on.map((d, i) => (
                        <div key={i}>
                          <span className="text-zinc-500">      - </span>
                          {d}{"\n"}
                        </div>
                      ))}
                    </>
                  )}
                </div>
              ))}
            </div>
          ))}
          {g.volumes.length > 0 && (
            <>
              <span className="text-zinc-500">  # group volumes:</span>{"\n"}
              {g.volumes.map((v) => (
                <div key={v}>
                  <span className="text-zinc-500">  - </span>
                  {v}{"\n"}
                </div>
              ))}
            </>
          )}
        </div>
      ))}
    </pre>
  );
}


/* ── Preview Dialog ───────────────────────────────────── */

import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import type { GroupPreview, DeploymentData } from "@/lib/projectsApi";

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

function VarRow({ v, values, statuses, instSlug, onUpdate, onUpdateStatus, t }: {
  v: ProductVariable;
  values: Record<string, string>;
  statuses: Record<string, InstanceVariableStatus>;
  instSlug: string;
  onUpdate: (name: string, val: string) => void;
  onUpdateStatus: (name: string, status: InstanceVariableStatus) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const isUndeclared = v.undeclared === true;
  const currentStatus = statuses[v.name] ?? "keep";
  const hasGenerator = Boolean(v.generate && v.generate !== "null");
  const hasValue = Boolean(String(values[v.name] ?? "").trim());
  const isResolved = !isUndeclared && (hasGenerator || hasValue);
  // Rewrite ${VARNAME} → ${INSTSLUG_VARNAME} for secrets so the badge matches
  // what actually appears in the generated .env.
  const displayedSyntax =
    v.type === "secret" && instSlug
      ? v.syntax.replace(/\$\{([A-Z_][A-Z0-9_]*)\}/g, (_, n) => `\${${instSlug}_${n}}`)
      : v.syntax;
  const badgeColorClass = isUndeclared
    ? "border-red-500 text-red-500"
    : isResolved
      ? "border-green-500 text-green-600"
      : v.type === "secret"
        ? "border-orange-400 text-orange-500"
        : "border-blue-400 text-blue-500";
  return (
    <div className="flex items-start gap-3">
      <div className="w-48 shrink-0 pt-1.5">
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className={`text-[8px] font-mono ${badgeColorClass}`}>
            {displayedSyntax}
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
  const [statuses, setStatuses] = useState<Record<string, InstanceVariableStatus>>(
    (instance.variable_statuses ?? {}) as Record<string, InstanceVariableStatus>,
  );
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  // Rewrite ${VAR} references to ${<INSTSLUG>_VAR} for any VAR declared as a
  // secret in the recipe. Used in the Connectors + API panels so the display
  // matches what actually lands in the generated .env.
  const instSlugForDisplay = instance.instance_name.toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const secretNames = new Set((productVars ?? []).filter((v) => v.type === "secret").map((v) => v.name));
  function rewriteSecretRefs(value: string): string {
    if (!value) return value;
    return value.replace(/\$\{([A-Z_][A-Z0-9_]*)\}/g, (m, name) => {
      if (secretNames.has(name)) return `\${${instSlugForDisplay}_${name}}`;
      return m;
    });
  }

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
                      <VarRow key={v.name} v={v} values={values} statuses={statuses} instSlug={instSlugForDisplay} onUpdate={updateValue} onUpdateStatus={updateStatus} t={t} />
                    ))}
                  </div>
                </CollapsibleSection>
              )}

              {/* Sub-block: Secrets ${} */}
              {productVars.some((v) => v.type === "secret") && (
                <CollapsibleSection title={t("projects.section_secrets")} count={productVars.filter((v) => v.type === "secret").length}>
                  <div className="space-y-2">
                    {productVars.filter((v) => v.type === "secret").map((v) => (
                      <VarRow key={v.name} v={v} values={values} statuses={statuses} instSlug={instSlugForDisplay} onUpdate={updateValue} onUpdateStatus={updateStatus} t={t} />
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
                              const rewritten = rewriteSecretRefs(v);
                              return (
                                <div key={k} className="flex items-center gap-2 text-[10px] font-mono">
                                  <span className="text-muted-foreground">{k}</span>
                                  <span className="text-muted-foreground">=</span>
                                  <span className={rewritten.startsWith("${") ? "text-orange-500" : "text-blue-500"}>{rewritten}</span>
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
                        <div><span className="text-muted-foreground">auth:</span> {apiDef.auth_header} {apiDef.auth_prefix} <span className="text-orange-500">{rewriteSecretRefs(apiDef.auth_secret_ref ?? "")}</span></div>
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

/* ── Deploy preview : Scripts panel ──────────────────── */

function DeployScriptsPanel({ groupIds, envText, t }: {
  groupIds: string[];
  envText: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const linksQueries = useQuery({
    queryKey: ["deploy-scripts", groupIds.join(",")],
    queryFn: async () => {
      const all = await Promise.all(groupIds.map((gid) => groupScriptsApi.list(gid)));
      return all.flat();
    },
  });
  const scriptsQuery = useQuery({ queryKey: ["scripts"], queryFn: () => scriptsApi.list() });

  const links = linksQueries.data ?? [];
  const scripts = scriptsQuery.data ?? [];

  // Parse envText into a map
  const envMap: Record<string, string> = {};
  for (const line of envText.split("\n")) {
    const s = line.trim();
    if (!s || s.startsWith("#") || !line.includes("=")) continue;
    const [k, ...rest] = line.split("=");
    envMap[k!.trim()] = rest.join("=").trim();
  }

  function resolveValue(raw: string, groupName: string): { resolved: string; ok: boolean } {
    let unresolved = false;
    const prefix = (groupName || "").toUpperCase().replace(/[^A-Z0-9]/g, "_");
    const out = raw.replace(/\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)/g, (m, g1, g2) => {
      const key = g1 || g2;
      if (!key) { unresolved = true; return m; }
      if (envMap[key] !== undefined && envMap[key] !== "") return envMap[key];
      const prefixed = prefix ? `${prefix}_${key}` : key;
      if (envMap[prefixed] !== undefined && envMap[prefixed] !== "") return envMap[prefixed];
      unresolved = true;
      return m;
    });
    if (!raw) unresolved = true;
    return { resolved: out, ok: !unresolved };
  }

  if (linksQueries.isLoading) {
    return <p className="p-4 text-[12px] text-muted-foreground">…</p>;
  }
  if (links.length === 0) {
    return (
      <p className="p-4 text-[12px] text-muted-foreground italic">
        {t("scripts.deploy_tab_empty")}
      </p>
    );
  }

  const before = links.filter((l) => l.timing === "before").sort((a, b) => a.position - b.position);
  const after = links.filter((l) => l.timing === "after").sort((a, b) => a.position - b.position);

  return (
    <div className="p-2 space-y-3 max-h-[60vh] overflow-auto">
      {[
        { timing: "before" as const, label: t("scripts.group_timing_before"), items: before },
        { timing: "after" as const, label: t("scripts.group_timing_after"), items: after },
      ].map((section) => (
        section.items.length > 0 && (
          <div key={section.timing}>
            <div className="text-[11px] font-semibold uppercase text-muted-foreground mb-1">
              {section.label}
            </div>
            <div className="space-y-2">
              {section.items.map((l) => {
                const script = scripts.find((s) => s.id === l.script_id);
                const declared = script?.input_variables ?? [];
                return (
                  <div key={l.id} className="border rounded p-2 bg-zinc-950 text-zinc-300 text-[12px]">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono font-semibold">{l.script_name}</span>
                      <span className="text-[10px] text-zinc-500">→ {l.machine_name}</span>
                      {l.trigger_rules.length > 0 && (
                        <span className="text-[9px] bg-zinc-800 text-zinc-300 px-1.5 py-0.5 rounded">
                          {l.trigger_rules.length} rule(s)
                        </span>
                      )}
                    </div>
                    {declared.length === 0 ? (
                      <p className="text-[10px] text-zinc-500 italic">{t("scripts.deploy_tab_no_inputs")}</p>
                    ) : (
                      <div className="space-y-0.5 font-mono">
                        {declared.map((iv) => {
                          const raw = l.input_values[iv.name] ?? "";
                          const { resolved, ok } = resolveValue(raw, l.group_name || "");
                          const color = ok ? "text-green-400" : "text-red-400";
                          return (
                            <div key={iv.name}>
                              <span className="text-zinc-500">{iv.name}</span>
                              <span className="text-zinc-600">=</span>
                              <span className={color}>{resolved || "(empty)"}</span>
                              {raw !== resolved && (
                                <span className="text-zinc-600 ml-2 text-[10px]">← {raw}</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )
      ))}
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
  const [inputValues, setInputValues] = useState<Record<string, string>>({});
  const [inputStatuses, setInputStatuses] = useState<Record<string, InputStatus>>({});
  const [inputsOpen, setInputsOpen] = useState(true);
  const [triggerRules, setTriggerRules] = useState<TriggerRule[]>([]);
  const [rulesOpen, setRulesOpen] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setScriptId(initial.script_id);
      setMachineId(initial.machine_id);
      setTiming(initial.timing);
      setPosition(String(initial.position));
      setMappingText(Object.entries(initial.env_mapping).map(([k, v]) => `${k}=${v}`).join("\n"));
      setInputValues(initial.input_values ?? {});
      setInputStatuses((initial.input_statuses ?? {}) as Record<string, InputStatus>);
      setTriggerRules(initial.trigger_rules ?? []);
    } else {
      setScriptId(""); setMachineId(""); setTiming("before"); setPosition("0");
      setMappingText(""); setInputValues({}); setInputStatuses({}); setTriggerRules([]);
    }
    setInputsOpen(true);
    setRulesOpen(true);
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // When a script with an execute_on_types_named constraint is selected,
  // show only machines of that variant. Otherwise show all.
  const selectedScript = scripts.find((s) => s.id === scriptId);
  const requiredTypeId = selectedScript?.execute_on_types_named ?? null;
  const declaredInputs = selectedScript?.input_variables ?? [];

  // Prefill defaults when picking a script that has declared defaults
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

          {declaredInputs.length > 0 && (
            <div className="border-t pt-3">
              <button
                type="button"
                className="flex items-center gap-1 text-[11px] font-semibold w-full text-left"
                onClick={() => setInputsOpen((v) => !v)}
              >
                {inputsOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {t("scripts.group_inputs_title", { count: String(declaredInputs.length) })}
              </button>
              {inputsOpen && (
                <div className="mt-2 space-y-2">
                  {declaredInputs.map((iv) => {
                    const s = inputStatuses[iv.name] ?? "keep";
                    return (
                      <div key={iv.name}>
                        <Label className="text-[10px]">
                          <span className="font-mono">{iv.name}</span>
                          {iv.description && <span className="text-muted-foreground ml-1">— {iv.description}</span>}
                        </Label>
                        <div className="flex gap-1 mt-1">
                          <Input
                            value={inputValues[iv.name] ?? ""}
                            onChange={(e) => setInputValues({ ...inputValues, [iv.name]: e.target.value })}
                            className="font-mono text-[11px] flex-1"
                            placeholder={iv.default || "${ENV_VAR} ou valeur littérale"}
                          />
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
            </div>
          )}

          <div className="border-t pt-3">
            <div className="flex items-center justify-between">
              <button
                type="button"
                className="flex items-center gap-1 text-[11px] font-semibold"
                onClick={() => setRulesOpen((v) => !v)}
              >
                {rulesOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {t("scripts.group_rules_title", { count: String(triggerRules.length) })}
              </button>
              {rulesOpen && (
                <Button
                  type="button" size="sm" variant="outline" className="h-6 text-[10px]"
                  onClick={() => setTriggerRules([...triggerRules, { variable: "", op: "equals", value: "" }])}
                >
                  <Plus className="w-3 h-3" />
                  {t("scripts.group_rules_add")}
                </Button>
              )}
            </div>
            {rulesOpen && triggerRules.length > 0 && (
              <div className="mt-2 space-y-1">
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
            {rulesOpen && (
              <p className="text-[10px] text-muted-foreground mt-1">{t("scripts.group_rules_hint")}</p>
            )}
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
                  input_values: inputValues,
                  input_statuses: inputStatuses,
                  trigger_rules: triggerRules.filter((r) => r.variable.trim()),
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
