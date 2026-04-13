import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  BookMarked,
  Cog,
  Copy,
  Eye,
  FileCode2,
  MessageSquare,
  Play,
  Plus,
  PlugZap,
  Save,
  TerminalSquare,
  Trash2,
  UserRoundCog,
  X,
} from "lucide-react";
import { useDockerfiles, useDockerfileDetail } from "@/hooks/useDockerfiles";
import { useRoles } from "@/hooks/useRoles";
import { useMCPCatalog, useSkillsCatalog } from "@/hooks/useCatalogs";
import {
  useAgent,
  useAgentProfiles,
  useAgents,
  useConfigPreview,
} from "@/hooks/useAgents";
import { useRoleDetail } from "@/hooks/useRoleDocuments";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import { secretsApi } from "@/lib/secretsApi";
import { useVault } from "@/hooks/useVault";
import { userSecretsApi } from "@/lib/userSecretsApi";
import { containersApi } from "@/lib/containersApi";
import { ChatWindow } from "@/components/ChatWindow";
import { TerminalWindow } from "@/components/TerminalWindow";
import { ProfileInlineEditor } from "@/components/ProfileInlineEditor";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PromptDialog } from "@/components/PromptDialog";
import { PageShell } from "@/components/layout/PageHeader";
import { slugify } from "@/lib/slugify";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  agentsApi,
  type AgentCreatePayload,
  type AgentMCPBinding,
  type AgentProfileSummary,
  type AgentSkillBinding,
  type ConfigPreview,
  type NetworkMode,
} from "@/lib/agentsApi";

type EnvEntry = { key: string; value: string };

interface FormState {
  slug: string;
  display_name: string;
  description: string;
  dockerfile_id: string;
  role_id: string;
  env_entries: EnvEntry[];
  timeout_seconds: number;
  workspace_path: string;
  network_mode: NetworkMode;
  graceful_shutdown_secs: number;
  force_kill_delay_secs: number;
  mcp_bindings: AgentMCPBinding[];
  skill_bindings: AgentSkillBinding[];
}

const EMPTY_FORM: FormState = {
  slug: "",
  display_name: "",
  description: "",
  dockerfile_id: "",
  role_id: "",
  env_entries: [],
  timeout_seconds: 3600,
  workspace_path: "/workspace",
  network_mode: "bridge",
  graceful_shutdown_secs: 30,
  force_kill_delay_secs: 10,
  mcp_bindings: [],
  skill_bindings: [],
};

function envObjectToEntries(obj: Record<string, string>): EnvEntry[] {
  return Object.entries(obj).map(([key, value]) => ({ key, value }));
}

function envEntriesToObject(entries: EnvEntry[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of entries) {
    if (e.key.trim()) out[e.key.trim()] = e.value;
  }
  return out;
}

export function AgentEditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const { state: vaultState, decryptSecret } = useVault();

  const { agent, isLoading: agentLoading, updateMutation } = useAgent(
    isNew ? undefined : id,
  );
  const { createMutation, deleteMutation, duplicateMutation } = useAgents();
  const { dockerfiles } = useDockerfiles();
  const { roles } = useRoles();
  const { mcps } = useMCPCatalog();
  const { skills } = useSkillsCatalog();
  const [previewProfileId, setPreviewProfileId] = useState<string | null>(null);
  const previewQuery = useConfigPreview(
    isNew ? undefined : id,
    previewProfileId ?? undefined,
  );
  const profilesHook = useAgentProfiles(isNew ? undefined : id);
  const roleDetailQuery = useRoleDetail(isNew ? null : agent?.role_id ?? null);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const dockerfileDetailQuery = useDockerfileDetail(form.dockerfile_id || null);
  const [error, setError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [preview, setPreview] = useState<ConfigPreview | null>(null);
  const [slugTouched, setSlugTouched] = useState(false);
  const [editingProfile, setEditingProfile] =
    useState<AgentProfileSummary | null>(null);
  const [showAddProfileDialog, setShowAddProfileDialog] = useState(false);
  const [addProfileError, setAddProfileError] = useState<string | null>(null);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [deleteProfileTarget, setDeleteProfileTarget] = useState<{ id: string; name: string } | null>(null);
  const [showDeleteAgentDialog, setShowDeleteAgentDialog] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedFiles, setGeneratedFiles] = useState<{ path: string; content: string }[]>([]);
  const [selectedGenFile, setSelectedGenFile] = useState<string | null>(null);
  const [chatOpenFor, setChatOpenFor] = useState<string | null>(null);
  const [terminalContainer, setTerminalContainer] = useState<{ id: string; name: string } | null>(null);
  const [runningContainerId, setRunningContainerId] = useState<string | null>(null);

  useEffect(() => {
    if (!isNew && agent) {
      setForm({
        slug: agent.slug,
        display_name: agent.display_name,
        description: agent.description,
        dockerfile_id: agent.dockerfile_id,
        role_id: agent.role_id,
        env_entries: envObjectToEntries(agent.env_vars),
        timeout_seconds: agent.timeout_seconds,
        workspace_path: agent.workspace_path,
        network_mode: agent.network_mode,
        graceful_shutdown_secs: agent.graceful_shutdown_secs,
        force_kill_delay_secs: agent.force_kill_delay_secs,
        mcp_bindings: agent.mcp_bindings,
        skill_bindings: agent.skill_bindings,
      });
    }
  }, [isNew, agent]);

  useEffect(() => {
    if (!isNew && id) {
      agentsApi.listGenerated(id).then(setGeneratedFiles).catch(() => {});
    }
  }, [isNew, id]);

  const availableMCPs = useMemo(() => mcps ?? [], [mcps]);
  const availableSkills = useMemo(() => skills ?? [], [skills]);

  const dockerfileEnvKeys = useMemo(() => {
    const files = dockerfileDetailQuery.data?.files ?? [];
    const paramsFile = files.find((f) => f.path === "Dockerfile.json");
    if (!paramsFile) return [];
    try {
      const parsed = JSON.parse(paramsFile.content);
      const envs = parsed?.docker?.Environments ?? {};
      return Object.keys(envs);
    } catch {
      return [];
    }
  }, [dockerfileDetailQuery.data]);

  const referencedSecrets = useMemo(
    () =>
      form.env_entries
        .filter((e) => e.value.startsWith("$") && e.value.length > 1)
        .map((e) => e.value.slice(1)),
    [form.env_entries],
  );
  const envStatus = useEnvVarStatuses(referencedSecrets);

  const mcpName = (mcpId: string): string =>
    availableMCPs.find((m) => m.id === mcpId)?.name ?? mcpId;
  const mcpTransport = (mcpId: string): string =>
    availableMCPs.find((m) => m.id === mcpId)?.transport ?? "stdio";
  const skillName = (sid: string): string =>
    availableSkills.find((s) => s.id === sid)?.name ?? sid;

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "display_name" && isNew && !slugTouched) {
        next.slug = slugify(String(value), "-");
      }
      return next;
    });
  }

  function addEnv() {
    updateField("env_entries", [...form.env_entries, { key: "", value: "" }]);
  }

  function removeEnv(idx: number) {
    updateField(
      "env_entries",
      form.env_entries.filter((_, i) => i !== idx),
    );
  }

  function setEnv(idx: number, field: keyof EnvEntry, value: string) {
    const next = [...form.env_entries];
    const entry = next[idx];
    if (!entry) return;
    next[idx] = { ...entry, [field]: value };
    updateField("env_entries", next);
  }

  function addMCP() {
    const firstAvailable = availableMCPs.find(
      (m) => !form.mcp_bindings.some((b) => b.mcp_server_id === m.id),
    );
    if (!firstAvailable) return;
    updateField("mcp_bindings", [
      ...form.mcp_bindings,
      {
        mcp_server_id: firstAvailable.id,
        parameters_override: {},
        position: form.mcp_bindings.length,
      },
    ]);
  }

  function removeMCP(idx: number) {
    updateField(
      "mcp_bindings",
      form.mcp_bindings.filter((_, i) => i !== idx),
    );
  }

  function setMCPOverride(idx: number, raw: string) {
    const next = [...form.mcp_bindings];
    const entry = next[idx];
    if (!entry) return;
    try {
      next[idx] = { ...entry, parameters_override: JSON.parse(raw || "{}") };
      updateField("mcp_bindings", next);
      setError(null);
    } catch {
      setError(`Invalid JSON in MCP #${idx + 1} override`);
    }
  }

  function addSkill() {
    const firstAvailable = availableSkills.find(
      (s) => !form.skill_bindings.some((b) => b.skill_id === s.id),
    );
    if (!firstAvailable) return;
    updateField("skill_bindings", [
      ...form.skill_bindings,
      { skill_id: firstAvailable.id, position: form.skill_bindings.length },
    ]);
  }

  function removeSkill(idx: number) {
    updateField(
      "skill_bindings",
      form.skill_bindings.filter((_, i) => i !== idx),
    );
  }

  function buildPayload(): AgentCreatePayload {
    return {
      slug: form.slug,
      display_name: form.display_name,
      description: form.description,
      dockerfile_id: form.dockerfile_id,
      role_id: form.role_id,
      env_vars: envEntriesToObject(form.env_entries),
      timeout_seconds: form.timeout_seconds,
      workspace_path: form.workspace_path,
      network_mode: form.network_mode,
      graceful_shutdown_secs: form.graceful_shutdown_secs,
      force_kill_delay_secs: form.force_kill_delay_secs,
      mcp_bindings: form.mcp_bindings,
      skill_bindings: form.skill_bindings,
    };
  }

  async function handleSave() {
    setError(null);
    try {
      if (isNew) {
        const created = await createMutation.mutateAsync(buildPayload());
        navigate(`/agents/${created.id}`);
      } else {
        const { slug: _slug, ...updatePayload } = buildPayload();
        void _slug;
        await updateMutation.mutateAsync(updatePayload);
      }
    } catch (e) {
      const err = e as {
        response?: { status?: number; data?: { detail?: string } };
      };
      if (err.response?.status === 409) {
        setError(t("agent_editor.error_duplicate_slug"));
      } else if (err.response?.status === 400) {
        setError(t("agent_editor.error_invalid_reference"));
      } else {
        setError(err.response?.data?.detail ?? t("agent_editor.error_generic"));
      }
    }
  }

  async function handlePreview(profileId: string | null = null) {
    if (isNew || !id) return;
    setPreviewProfileId(profileId);
    await Promise.resolve();
    const result = await previewQuery.refetch();
    if (result.data) {
      setPreview(result.data);
      setShowPreview(true);
    }
  }

  async function handleAddProfile(values: Record<string, string>) {
    if (isNew || !id) return;
    setAddProfileError(null);
    try {
      const created = await profilesHook.createMutation.mutateAsync({
        name: values.name ?? "",
        description: values.description ?? "",
        document_ids: [],
      });
      setEditingProfile(created);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setAddProfileError(detail ?? t("agent_editor.error_generic"));
      throw e;
    }
  }

  function handleDeleteProfile(profile: AgentProfileSummary) {
    setDeleteProfileTarget({ id: profile.id, name: profile.name });
  }

  async function handleSaveProfileDocs(
    profile: AgentProfileSummary,
    document_ids: string[],
  ) {
    await profilesHook.updateMutation.mutateAsync({
      profileId: profile.id,
      payload: { document_ids },
    });
  }

  async function handleDuplicateSubmit(values: Record<string, string>) {
    if (isNew || !id) return;
    const copy = await duplicateMutation.mutateAsync({
      id,
      slug: values.slug ?? "",
      displayName: values.displayName ?? "",
    });
    navigate(`/agents/${copy.id}`);
  }

  function handleDelete() {
    if (isNew || !id) return;
    setShowDeleteAgentDialog(true);
  }

  if (!isNew && agentLoading)
    return (
      <PageShell>
        <p className="text-muted-foreground">{t("secrets.loading")}</p>
      </PageShell>
    );

  const title = isNew
    ? t("agent_editor.title_new")
    : form.display_name || t("agent_editor.title_new");

  return (
    <PageShell maxWidth="5xl">
      {/* Back link */}
      <button
        type="button"
        onClick={() => navigate("/agents")}
        className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground mb-5"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        {t("agent_editor.back_to_agents")}
      </button>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <h1 className="text-[20px] font-semibold text-foreground truncate">
          {title}
        </h1>
        {!isNew && form.slug && (
          <span className="text-muted-foreground font-mono text-[12px]">
            {form.slug}
          </span>
        )}

        <div className="flex items-center gap-2 ml-auto">
          <Button size="sm" onClick={handleSave}>
            <Save className="w-3.5 h-3.5" />
            {t("agent_editor.save")}
          </Button>

          {!isNew && (
            <>
              <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => handlePreview(null)}
                  title={t("agent_editor.preview_identity_only")}
                >
                  <Eye className="w-3.5 h-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={() => setShowDuplicateDialog(true)}
                  title={t("agent_editor.duplicate_button")}
                >
                  <Copy className="w-3.5 h-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-destructive"
                  onClick={() => setShowDeleteAgentDialog(true)}
                  title={t("agents.delete_button")}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>

              <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  disabled={generating}
                  title={t("agent_editor.generate_button")}
                  onClick={async () => {
                    if (!id) return;
                    setGenerating(true);
                    try {
                      let secrets: Record<string, string> = {};
                      if (vaultState === "unlocked") {
                        try {
                          const list = await userSecretsApi.list();
                          for (const s of list) {
                            try { secrets[s.name] = decryptSecret(s.ciphertext, s.iv); } catch { /* skip */ }
                          }
                        } catch { /* no vault */ }
                      }
                      await agentsApi.generate(id, { secrets });
                      const files = await agentsApi.listGenerated(id);
                      setGeneratedFiles(files);
                    } catch (e) {
                      setError(String(e));
                    } finally {
                      setGenerating(false);
                    }
                  }}
                >
                  <Cog className={`w-3.5 h-3.5 ${generating ? "animate-spin" : ""}`} />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  title={t("agent_editor.launch_button")}
                  onClick={async () => {
                    if (!form.dockerfile_id) return;
                    try {
                      let secrets: Record<string, string> = {};
                      if (vaultState === "unlocked") {
                        try {
                          const list = await userSecretsApi.list();
                          for (const s of list) {
                            try { secrets[s.name] = decryptSecret(s.ciphertext, s.iv); } catch { /* skip */ }
                          }
                        } catch { /* no vault */ }
                      }
                      const c = await containersApi.run(form.dockerfile_id, secrets);
                      setRunningContainerId(c.id);
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  <Play className="w-3.5 h-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  title={t("agent_editor.chat_button")}
                  disabled={!form.dockerfile_id}
                  onClick={() => setChatOpenFor(form.dockerfile_id)}
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  title={t("agent_editor.terminal_button")}
                  disabled={!runningContainerId}
                  onClick={() => {
                    if (runningContainerId) {
                      setTerminalContainer({ id: runningContainerId, name: form.slug || "agent" });
                    }
                  }}
                >
                  <TerminalSquare className="w-3.5 h-3.5" />
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      {error && (
        <Card className="mb-4 border-destructive/40 bg-destructive/5">
          <CardContent className="pt-5 pb-5">
            <p role="alert" className="text-destructive text-[13px]">
              {error}
            </p>
          </CardContent>
        </Card>
      )}

      {/* General */}
      <SectionLabel>{t("agent_editor.section_general")}</SectionLabel>
      <Card className="mb-6">
        <CardContent className="pt-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>{t("agent_editor.display_name")}</Label>
              <Input
                value={form.display_name}
                onChange={(e) => updateField("display_name", e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>{t("agent_editor.slug")}</Label>
              <Input
                value={form.slug}
                onChange={(e) => {
                  setSlugTouched(true);
                  updateField("slug", e.target.value);
                }}
                disabled={!isNew}
                className="font-mono text-[12px]"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.description")}</Label>
            <Textarea
              value={form.description}
              onChange={(e) => updateField("description", e.target.value)}
              rows={2}
            />
          </div>
        </CardContent>
      </Card>

      {/* Composition — brick cards */}
      <div className="flex items-center justify-between mb-3">
        <SectionLabel className="mb-0">
          {t("agent_editor.section_composition")}
        </SectionLabel>
        <span className="text-muted-foreground text-[12px]">
          {1 +
            1 +
            form.mcp_bindings.length +
            form.skill_bindings.length}{" "}
          {t("agent_editor.bricks_assembled")}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Dockerfile brick */}
        <BrickCard
          icon={
            <div className="w-8 h-8 rounded-md bg-blue-50 dark:bg-blue-950/40 border border-blue-100 dark:border-blue-900/50 flex items-center justify-center">
              <FileCode2 className="w-4 h-4 text-blue-600 dark:text-blue-400" />
            </div>
          }
          kind={t("agent_editor.section_dockerfile")}
        >
          <Select
            value={form.dockerfile_id}
            onValueChange={(v) => updateField("dockerfile_id", v)}
          >
            <SelectTrigger className="mt-2">
              <SelectValue placeholder="—" />
            </SelectTrigger>
            <SelectContent>
              {(dockerfiles ?? []).map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </BrickCard>

        {/* Role brick */}
        <BrickCard
          icon={
            <div className="w-8 h-8 rounded-md bg-violet-50 dark:bg-violet-950/40 border border-violet-100 dark:border-violet-900/50 flex items-center justify-center">
              <UserRoundCog className="w-4 h-4 text-violet-600 dark:text-violet-400" />
            </div>
          }
          kind={t("agent_editor.section_role")}
        >
          <Select
            value={form.role_id}
            onValueChange={(v) => updateField("role_id", v)}
          >
            <SelectTrigger className="mt-2">
              <SelectValue placeholder="—" />
            </SelectTrigger>
            <SelectContent>
              {(roles ?? []).map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </BrickCard>

        {/* MCPs brick — spans 2 columns */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-md bg-cyan-50 dark:bg-cyan-950/40 border border-cyan-100 dark:border-cyan-900/50 flex items-center justify-center">
                  <PlugZap className="w-4 h-4 text-cyan-600 dark:text-cyan-400" />
                </div>
                <div>
                  <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                    {t("agent_editor.section_mcps")}
                  </div>
                  <div className="text-[14px] font-semibold text-foreground -mt-0.5">
                    {form.mcp_bindings.length}{" "}
                    {t("agent_editor.mcp_count_suffix")}
                  </div>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={addMCP}>
                <Plus className="w-3.5 h-3.5" />
                {t("agent_editor.mcp_add_short")}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {form.mcp_bindings.length === 0 ? (
              <p className="text-muted-foreground text-[12px] italic">
                {t("agent_editor.mcp_empty")}
              </p>
            ) : (
              <div className="space-y-2">
                {form.mcp_bindings.map((b, idx) => (
                  <div
                    key={`${b.mcp_server_id}-${idx}`}
                    className="border rounded-md p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[13px] font-semibold text-foreground truncate">
                          {mcpName(b.mcp_server_id)}
                        </span>
                        <Badge variant="secondary" className="font-mono text-[10px]">
                          {mcpTransport(b.mcp_server_id)}
                        </Badge>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMCP(idx)}
                        aria-label={t("agent_editor.mcp_remove")}
                      >
                        <X className="w-3.5 h-3.5 text-muted-foreground" />
                      </Button>
                    </div>
                    <div className="mt-2">
                      <Label className="text-[11px]">
                        {t("agent_editor.mcp_override_label")}
                      </Label>
                      <Textarea
                        defaultValue={JSON.stringify(
                          b.parameters_override,
                          null,
                          2,
                        )}
                        onBlur={(e) => setMCPOverride(idx, e.target.value)}
                        rows={3}
                        className="font-mono text-[11px] mt-1"
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Skills brick — spans 2 columns */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-100 dark:border-amber-900/50 flex items-center justify-center">
                  <BookMarked className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                    {t("agent_editor.section_skills")}
                  </div>
                  <div className="text-[14px] font-semibold text-foreground -mt-0.5">
                    {form.skill_bindings.length}{" "}
                    {t("agent_editor.skill_count_suffix")}
                  </div>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={addSkill}>
                <Plus className="w-3.5 h-3.5" />
                {t("agent_editor.skill_add_short")}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {form.skill_bindings.length === 0 ? (
              <p className="text-muted-foreground text-[12px] italic">
                {t("agent_editor.skill_empty")}
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {form.skill_bindings.map((b, idx) => (
                  <span
                    key={`${b.skill_id}-${idx}`}
                    className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-md bg-secondary text-[12px] text-foreground border"
                  >
                    <BookMarked className="w-3 h-3 text-muted-foreground" />
                    {skillName(b.skill_id)}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4 ml-1"
                      onClick={() => removeSkill(idx)}
                      aria-label={t("agent_editor.skill_remove")}
                    >
                      <X className="w-3 h-3" />
                    </Button>
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Profiles */}
      {!isNew && (
        <>
          <SectionLabel>{t("agent_editor.section_profiles")}</SectionLabel>
          <Card className="mb-6">
            <CardContent className="pt-5">
              <p className="text-muted-foreground text-[12px] mb-3">
                {t("agent_editor.profiles_subtitle")}
              </p>
              {(profilesHook.profiles ?? []).length === 0 ? (
                <p className="text-muted-foreground italic text-[13px] mb-3">
                  {t("agent_editor.profiles_empty")}
                </p>
              ) : (
                <ul className="space-y-2 mb-3">
                  {(profilesHook.profiles ?? []).map((p) => {
                    const isEditing = editingProfile?.id === p.id;
                    return (
                      <li
                        key={p.id}
                        className={cn(
                          "border rounded-md p-3",
                          isEditing && "bg-secondary/40",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-foreground text-[13px] truncate">
                                {p.name}
                              </span>
                              <Badge variant="outline">
                                {p.document_ids.length} docs
                              </Badge>
                            </div>
                            {p.description && (
                              <div className="text-[12px] text-muted-foreground mt-0.5">
                                {p.description}
                              </div>
                            )}
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setEditingProfile(isEditing ? null : p)
                            }
                          >
                            {isEditing
                              ? t("agent_editor.profile_close")
                              : t("agent_editor.profile_edit")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handlePreview(p.id)}
                            aria-label={t("agent_editor.preview_with_profile")}
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDeleteProfile(p)}
                            aria-label={t("agent_editor.profile_delete")}
                          >
                            <Trash2 className="w-3.5 h-3.5 text-destructive" />
                          </Button>
                        </div>
                        {isEditing && (
                          <ProfileInlineEditor
                            profile={p}
                            roleDetail={roleDetailQuery.data}
                            onSave={(doc_ids) =>
                              handleSaveProfileDocs(p, doc_ids)
                            }
                            onClose={() => setEditingProfile(null)}
                            onDelete={async () => {
                              await handleDeleteProfile(p);
                              setEditingProfile(null);
                            }}
                          />
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setAddProfileError(null);
                  setShowAddProfileDialog(true);
                }}
              >
                <Plus className="w-3.5 h-3.5" />
                {t("agent_editor.profile_add")}
              </Button>
            </CardContent>
          </Card>
        </>
      )}

      {/* Env vars */}
      <SectionLabel>{t("agent_editor.section_env")}</SectionLabel>
      <Card className="mb-6">
        <CardContent className="pt-5 space-y-2">
          {form.env_entries.map((entry, idx) => {
            const secretRef =
              entry.value.startsWith("$") && entry.value.length > 1
                ? entry.value.slice(1)
                : null;
            return (
              <div
                key={idx}
                className="flex flex-wrap items-center gap-2"
              >
                <Input
                  placeholder={t("agent_editor.env_key_placeholder")}
                  value={entry.key}
                  onChange={(e) => setEnv(idx, "key", e.target.value)}
                  className="font-mono text-[12px] w-40 md:w-48"
                />
                <Input
                  placeholder={t("agent_editor.env_value_placeholder")}
                  value={entry.value}
                  onChange={(e) => setEnv(idx, "value", e.target.value)}
                  className="flex-1 min-w-[180px] font-mono text-[12px]"
                />
                {secretRef && (
                  <EnvVarStatus
                    name={secretRef}
                    status={envStatus.data?.[secretRef]}
                    compact
                  />
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeEnv(idx)}
                  aria-label={t("agent_editor.env_remove")}
                >
                  <X className="w-3.5 h-3.5" />
                </Button>
              </div>
            );
          })}
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="outline" size="sm" onClick={addEnv}>
              <Plus className="w-3.5 h-3.5" />
              {t("agent_editor.env_add")}
            </Button>
            {dockerfileEnvKeys.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const existingKeys = new Set(form.env_entries.map((e) => e.key));
                  const toAdd = dockerfileEnvKeys.filter((k) => !existingKeys.has(k));
                  if (toAdd.length === 0) return;
                  setForm((prev) => ({
                    ...prev,
                    env_entries: [
                      ...prev.env_entries,
                      ...toAdd.map((k) => ({ key: k, value: `$${k}` })),
                    ],
                  }));
                }}
              >
                <FileCode2 className="w-3.5 h-3.5" />
                {t("agent_editor.env_from_dockerfile")}
              </Button>
            )}
            {referencedSecrets.some(
              (name) => envStatus.data?.[name] === "missing",
            ) && (
              <Button
                variant="outline"
                size="sm"
                className="text-amber-600"
                onClick={async () => {
                  const missing = referencedSecrets.filter(
                    (name) => envStatus.data?.[name] === "missing",
                  );
                  for (const name of missing) {
                    try {
                      await secretsApi.create({ var_name: name, value: "" });
                    } catch {
                      // already exists or error — skip
                    }
                  }
                  envStatus.refetch();
                }}
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                {t("agent_editor.env_create_missing")}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Lifecycle */}
      <SectionLabel>{t("agent_editor.section_lifecycle")}</SectionLabel>
      <Card className="mb-6">
        <CardContent className="pt-5 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.timeout")}</Label>
            <Input
              type="number"
              value={form.timeout_seconds}
              onChange={(e) =>
                updateField("timeout_seconds", Number(e.target.value))
              }
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.workspace_path")}</Label>
            <Input
              value={form.workspace_path}
              onChange={(e) => updateField("workspace_path", e.target.value)}
              className="font-mono text-[12px]"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.network_mode")}</Label>
            <Select
              value={form.network_mode}
              onValueChange={(v) =>
                updateField("network_mode", v as NetworkMode)
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="bridge">bridge</SelectItem>
                <SelectItem value="host">host</SelectItem>
                <SelectItem value="none">none</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.graceful_shutdown")}</Label>
            <Input
              type="number"
              value={form.graceful_shutdown_secs}
              onChange={(e) =>
                updateField("graceful_shutdown_secs", Number(e.target.value))
              }
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.force_kill_delay")}</Label>
            <Input
              type="number"
              value={form.force_kill_delay_secs}
              onChange={(e) =>
                updateField("force_kill_delay_secs", Number(e.target.value))
              }
            />
          </div>
        </CardContent>
      </Card>

      {/* Generated files explorer */}
      {!isNew && generatedFiles.length > 0 && (
        <>
          <SectionLabel>{t("agent_editor.section_generated")}</SectionLabel>
          <Card className="mb-6">
            <CardContent className="pt-5">
              <div className="flex gap-4 min-h-[200px]">
                <div className="w-48 shrink-0 border-r pr-3 overflow-y-auto max-h-[400px]">
                  <ul className="space-y-0.5">
                    {generatedFiles.map((f) => (
                      <li key={f.path}>
                        <button
                          type="button"
                          onClick={() => setSelectedGenFile(f.path)}
                          className={`w-full text-left px-2 py-1 rounded text-[12px] font-mono flex items-center gap-1.5 transition-colors ${
                            selectedGenFile === f.path
                              ? "bg-primary/10 text-primary"
                              : "hover:bg-secondary text-foreground"
                          }`}
                        >
                          <FileCode2 className="w-3 h-3 shrink-0 text-muted-foreground" />
                          <span className="truncate">{f.path}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="flex-1 min-w-0 overflow-auto">
                  {selectedGenFile ? (
                    <pre className="text-[12px] font-mono whitespace-pre-wrap bg-muted rounded p-3 max-h-[400px] overflow-auto">
                      {generatedFiles.find((f) => f.path === selectedGenFile)?.content ?? ""}
                    </pre>
                  ) : (
                    <p className="text-[12px] text-muted-foreground italic p-3">
                      {t("agent_editor.generated_select_file")}
                    </p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Assistant toggle */}
      {!isNew && agent && (
        <Card className="mb-6">
          <CardContent className="pt-5">
            <div className="flex items-center gap-3">
              <input
                id="is-assistant"
                type="checkbox"
                checked={agent.is_assistant}
                onChange={async (e) => {
                  try {
                    if (e.target.checked) {
                      await agentsApi.setAssistant(agent.id);
                    } else {
                      await agentsApi.clearAssistant();
                    }
                    qc.invalidateQueries({ queryKey: ["agents"] });
                    if (id) qc.invalidateQueries({ queryKey: ["agent", id] });
                    qc.invalidateQueries({ queryKey: ["assistant-agent"] });
                  } catch {
                    // silently fail
                  }
                }}
                className="h-4 w-4 rounded border border-input accent-primary"
              />
              <Label htmlFor="is-assistant" className="cursor-pointer">
                {t("assistant.toggle_label")}
              </Label>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1 ml-7">
              {t("assistant.toggle_hint")}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Danger zone */}
      {!isNew && (
        <div className="border-t pt-6">
          <Button variant="destructive" onClick={handleDelete}>
            <Trash2 className="w-4 h-4" />
            {t("agent_editor.delete_button")}
          </Button>
        </div>
      )}

      {/* Preview dialog */}
      <Dialog
        open={showPreview && preview !== null}
        onOpenChange={(o) => !o && setShowPreview(false)}
      >
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("agent_editor.preview_title")}</DialogTitle>
            <DialogDescription>
              {preview?.profile_name
                ? t("agent_editor.preview_profile_label", {
                    name: preview.profile_name,
                  })
                : t("agent_editor.preview_identity_only_label")}
            </DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="space-y-4">
              {preview.validation_errors.length > 0 ? (
                <div className="rounded-md bg-destructive/5 border border-destructive/20 p-3">
                  <div className="text-[13px] font-medium text-destructive mb-1">
                    {t("agent_editor.preview_errors")}
                  </div>
                  <ul className="text-[12px] text-destructive space-y-0.5 list-disc list-inside">
                    {preview.validation_errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200/60 dark:border-emerald-900/40 p-3">
                  <div className="text-[13px] font-medium text-emerald-900 dark:text-emerald-200">
                    {t("agent_editor.preview_no_errors")}
                  </div>
                </div>
              )}

              <PreviewBlock label="/config/prompt.md">
                {preview.prompt_md}
              </PreviewBlock>
              <PreviewBlock label="/config/mcp.json">
                {JSON.stringify(preview.mcp_json, null, 2)}
              </PreviewBlock>
              <PreviewBlock label="/config/tools.json">
                {JSON.stringify(preview.tools_json, null, 2)}
              </PreviewBlock>
              <PreviewBlock label="/config/.env">
                {preview.env_file || "(empty)"}
              </PreviewBlock>
              {preview.skills.length > 0 && (
                <div>
                  <div className="text-[12px] font-semibold text-muted-foreground font-mono mb-1">
                    /skills/
                  </div>
                  <ul className="text-[12px] list-disc list-inside">
                    {preview.skills.map((s) => (
                      <li key={s.skill_id}>{s.name}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPreview(false)}>
              {t("agent_editor.preview_close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PromptDialog
        open={showAddProfileDialog}
        onOpenChange={setShowAddProfileDialog}
        title={t("agent_editor.profile_dialog_title")}
        description={addProfileError ?? undefined}
        submitLabel={t("common.create")}
        onSubmit={handleAddProfile}
        fields={[
          { name: "name", label: t("agent_editor.profile_name_prompt") },
          {
            name: "description",
            label: t("agent_editor.profile_description_prompt"),
            required: false,
          },
        ]}
      />

      <PromptDialog
        open={showDuplicateDialog}
        onOpenChange={setShowDuplicateDialog}
        title={t("agents.duplicate_dialog_title")}
        submitLabel={t("common.duplicate")}
        onSubmit={handleDuplicateSubmit}
        fields={[
          { name: "displayName", label: t("agents.duplicate_prompt_name") },
          {
            name: "slug",
            label: t("agents.duplicate_prompt_slug"),
            autoSlugFrom: "displayName",
            slugSeparator: "-",
            monospace: true,
          },
        ]}
      />

      <ConfirmDialog
        open={deleteProfileTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteProfileTarget(null); }}
        title={t("agent_editor.profile_confirm_delete_title")}
        description={t("agent_editor.profile_confirm_delete_message", { name: deleteProfileTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteProfileTarget) await profilesHook.deleteMutation.mutateAsync(deleteProfileTarget.id);
        }}
      />

      <ConfirmDialog
        open={showDeleteAgentDialog}
        onOpenChange={setShowDeleteAgentDialog}
        title={t("agents.confirm_delete_title")}
        description={t("agents.confirm_delete_message", { name: form.display_name })}
        destructive
        onConfirm={async () => {
          if (id) {
            await deleteMutation.mutateAsync(id);
            navigate("/agents");
          }
        }}
      />
      {chatOpenFor && (
        <ChatWindow
          dockerfileId={chatOpenFor}
          onClose={() => setChatOpenFor(null)}
        />
      )}

      {terminalContainer && (
        <TerminalWindow
          containerId={terminalContainer.id}
          containerName={terminalContainer.name}
          onClose={() => setTerminalContainer(null)}
        />
      )}
    </PageShell>
  );
}

// ────────────────────────────────────────────────────────────────
// Internal helpers
// ────────────────────────────────────────────────────────────────

function SectionLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

function BrickCard({
  icon,
  kind,
  children,
}: {
  icon: React.ReactNode;
  kind: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="pt-5">
        <div className="flex items-start gap-2.5">
          {icon}
          <div className="flex-1 min-w-0">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
              {kind}
            </div>
            {children}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function PreviewBlock({
  label,
  children,
}: {
  label: string;
  children: string;
}) {
  return (
    <div>
      <div className="text-[12px] font-semibold text-muted-foreground font-mono mb-1">
        {label}
      </div>
      <pre className="bg-zinc-900 text-zinc-100 rounded-md p-3 text-[11px] font-mono max-h-48 overflow-auto whitespace-pre-wrap">
        {children}
      </pre>
    </div>
  );
}
