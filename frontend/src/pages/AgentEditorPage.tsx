import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookMarked,
  ChevronRight,
  Lock,
  Unlock,
  Copy,
  Eye,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  PlugZap,
  Save,
  TerminalSquare,
  Trash2,
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
import { EnvVarStatus } from "@/components/EnvVarStatus";
import { useVault } from "@/hooks/useVault";
import { userSecretsApi } from "@/lib/userSecretsApi";
import { containersApi } from "@/lib/containersApi";
import { ChatWindow } from "@/components/ChatWindow";
import { CodeEditor } from "@/components/CodeEditor";
import { FileTree } from "@/components/FileTree";
import { TerminalWindow } from "@/components/TerminalWindow";
import { ProfileInlineEditor } from "@/components/ProfileInlineEditor";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useEmptyLaunchKeys } from "@/hooks/useEmptyLaunchKeys";
import { VaultUnlockDialog } from "@/components/VaultUnlockDialog";
import { PromptDialog } from "@/components/PromptDialog";
import { PageShell } from "@/components/layout/PageHeader";
import { slugify } from "@/lib/slugify";
import { cn, maskEnvSecrets } from "@/lib/utils";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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


interface FieldOverride {
  value?: string;
  excluded?: boolean;
}

interface MountOverride {
  source?: string;
  excluded?: boolean;
}

interface FormState {
  slug: string;
  display_name: string;
  description: string;
  dockerfile_id: string;
  role_id: string;
  env_overrides: Record<string, FieldOverride>;
  mount_overrides: Record<string, MountOverride>;
  param_overrides: Record<string, FieldOverride>;
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
  env_overrides: {},
  mount_overrides: {},
  param_overrides: {},
  timeout_seconds: 3600,
  workspace_path: "/workspace",
  network_mode: "bridge",
  graceful_shutdown_secs: 30,
  force_kill_delay_secs: 10,
  mcp_bindings: [],
  skill_bindings: [],
};

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
  const [formDirty, setFormDirty] = useState(false);
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
  const [generatedFiles, setGeneratedFiles] = useState<
    { path: string; content: string; type?: "file" | "dir" }[]
  >([]);
  const [selectedGenFile, setSelectedGenFile] = useState<string | null>(null);
  const [chatOpenFor, setChatOpenFor] = useState<string | null>(null);
  const [decryptedSecrets, setDecryptedSecrets] = useState<Record<string, string> | null>(null);
  const [showVaultUnlock, setShowVaultUnlock] = useState(false);
  const [launchPendingSecrets, setLaunchPendingSecrets] = useState<
    Record<string, string> | null
  >(null);
  const dockerfileJsonContentForLaunch =
    dockerfileDetailQuery.data?.files.find(
      (f) => f.path === "Dockerfile.json",
    )?.content ?? null;
  const { emptyKeys: launchEmptyKeys } = useEmptyLaunchKeys({
    dockerfileJsonContent: dockerfileJsonContentForLaunch,
    decryptedSecrets,
  });

  async function decryptUserSecrets(): Promise<Record<string, string>> {
    if (vaultState !== "unlocked") return {};
    try {
      const list = await userSecretsApi.list();
      const result: Record<string, string> = {};
      for (const s of list) {
        try { result[s.name] = decryptSecret(s.ciphertext, s.iv); } catch { /* skip */ }
      }
      return result;
    } catch {
      return {};
    }
  }

  const vaultIsOpen = vaultState === "unlocked";

  // Auto-detect vault already unlocked on mount
  useEffect(() => {
    if (vaultIsOpen && !decryptedSecrets) {
      void decryptUserSecrets().then((s) => {
        if (Object.keys(s).length > 0) setDecryptedSecrets(s);
      });
    }
    if (!vaultIsOpen && decryptedSecrets) {
      setDecryptedSecrets(null);
    }
  }, [vaultIsOpen]); // eslint-disable-line react-hooks/exhaustive-deps

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
        env_overrides: (agent.env_vars as Record<string, unknown>)?.env_overrides as Record<string, FieldOverride> ?? {},
        mount_overrides: (agent.env_vars as Record<string, unknown>)?.mount_overrides as Record<string, MountOverride> ?? {},
        param_overrides: (agent.env_vars as Record<string, unknown>)?.param_overrides as Record<string, FieldOverride> ?? {},
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

  // Ctrl+S
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (formDirty) handleSave();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  // beforeunload
  useEffect(() => {
    if (!formDirty) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [formDirty]);

  const availableMCPs = useMemo(() => mcps ?? [], [mcps]);
  const availableSkills = useMemo(() => skills ?? [], [skills]);

  const currentTarget = useMemo(() => {
    const files = dockerfileDetailQuery.data?.files ?? [];
    const paramsFile = files.find((f) => f.path === "Dockerfile.json");
    if (!paramsFile) return null;
    try {
      const parsed = JSON.parse(paramsFile.content);
      return parsed.Target ?? null;
    } catch {
      return null;
    }
  }, [dockerfileDetailQuery.data]);

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

  const dockerfileMounts = useMemo(() => {
    const files = dockerfileDetailQuery.data?.files ?? [];
    const paramsFile = files.find((f) => f.path === "Dockerfile.json");
    if (!paramsFile) return [];
    try {
      const parsed = JSON.parse(paramsFile.content);
      return (parsed?.docker?.Mounts ?? []) as { source: string; target: string; readonly: boolean }[];
    } catch {
      return [];
    }
  }, [dockerfileDetailQuery.data]);

  const dockerfileParams = useMemo(() => {
    const files = dockerfileDetailQuery.data?.files ?? [];
    const paramsFile = files.find((f) => f.path === "Dockerfile.json");
    if (!paramsFile) return {} as Record<string, string>;
    try {
      const parsed = JSON.parse(paramsFile.content);
      return (parsed?.Params ?? {}) as Record<string, string>;
    } catch {
      return {} as Record<string, string>;
    }
  }, [dockerfileDetailQuery.data]);

  // Extract variable name from ${VAR}, ${VAR:-default}, or $VAR
  function extractSecretName(val: string): string | null {
    if (!val) return null;
    // ${VAR:-default} or ${VAR}
    const braceMatch = val.match(/^\$\{(\w+)(?::-[^}]*)?\}$/);
    if (braceMatch) return braceMatch[1] ?? null;
    // $VAR
    if (val.startsWith("$") && val.length > 1 && !val.startsWith("${")) return val.slice(1);
    return null;
  }

  // Get the base value from Dockerfile.json for a given env key
  function getBaseEnvValue(key: string): string {
    try {
      const files = dockerfileDetailQuery.data?.files ?? [];
      const pf = files.find((f) => f.path === "Dockerfile.json");
      if (!pf) return "";
      const parsed = JSON.parse(pf.content);
      return String((parsed?.docker?.Environments ?? {})[key] ?? "");
    } catch { return ""; }
  }

  // Resolve secret status from user vault (not platform secrets)
  const vaultSecretStatus = useMemo(() => {
    if (!decryptedSecrets) return {} as Record<string, "ok" | "empty" | "missing">;
    const status: Record<string, "ok" | "empty" | "missing"> = {};
    for (const key of dockerfileEnvKeys) {
      const override = form.env_overrides[key];
      if (override?.excluded) continue;
      const val = override?.value ?? getBaseEnvValue(key);
      const name = extractSecretName(val);
      if (!name) continue;
      if (name in decryptedSecrets) {
        status[name] = decryptedSecrets[name] ? "ok" : "empty";
      } else {
        status[name] = "missing";
      }
    }
    return status;
  }, [dockerfileEnvKeys, form.env_overrides, decryptedSecrets, dockerfileDetailQuery.data]);

  const mcpName = (mcpId: string): string =>
    availableMCPs.find((m) => m.id === mcpId)?.name ?? mcpId;
  const mcpTransport = (mcpId: string): string =>
    availableMCPs.find((m) => m.id === mcpId)?.transport ?? "stdio";
  const mcpDetails = (mcpId: string) =>
    availableMCPs.find((m) => m.id === mcpId);
  const skillName = (sid: string): string =>
    availableSkills.find((s) => s.id === sid)?.name ?? sid;

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setFormDirty(true);
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "display_name" && isNew && !slugTouched) {
        next.slug = slugify(String(value), "-");
      }
      return next;
    });
  }

  function setEnvOverride(key: string, override: FieldOverride | undefined) {
    const next = { ...form.env_overrides };
    if (override === undefined) {
      delete next[key];
    } else {
      next[key] = override;
    }
    updateField("env_overrides", next);
  }

  function setMountOverride(target: string, override: MountOverride | undefined) {
    const next = { ...form.mount_overrides };
    if (override === undefined) delete next[target];
    else next[target] = override;
    updateField("mount_overrides", next);
  }

  function setParamOverride(key: string, override: FieldOverride | undefined) {
    const next = { ...form.param_overrides };
    if (override === undefined) delete next[key];
    else next[key] = override;
    updateField("param_overrides", next);
  }

  function removeMCP(idx: number) {
    updateField(
      "mcp_bindings",
      form.mcp_bindings.filter((_, i) => i !== idx),
    );
  }

  /* setMCPOverride — kept as reference for raw JSON fallback if needed
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
  } */

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
      env_vars: {
        env_overrides: form.env_overrides,
        mount_overrides: form.mount_overrides,
        param_overrides: form.param_overrides,
      } as unknown as Record<string, string>,
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
        setFormDirty(false);
        navigate(`/agents/${created.id}`);
      } else {
        const { slug: _slug, ...updatePayload } = buildPayload();
        void _slug;
        await updateMutation.mutateAsync(updatePayload);
        setFormDirty(false);
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
                  className="h-7 w-7 active:scale-100 active:translate-y-0 active:shadow-none"
                  disabled={generating}
                  title={t("agent_editor.generate_button")}
                  onClick={async () => {
                    if (!id) return;
                    setGenerating(true);
                    try {
                      const secrets = decryptedSecrets ?? await decryptUserSecrets();
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
                  <RefreshCw
                    className={`w-3.5 h-3.5 ${generating ? "animate-spin" : ""}`}
                  />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  title={t("agent_editor.launch_button")}
                  onClick={async () => {
                    if (!form.dockerfile_id) return;
                    try {
                      const secrets = decryptedSecrets ?? await decryptUserSecrets();
                      if (launchEmptyKeys.length > 0) {
                        setLaunchPendingSecrets(secrets);
                        return;
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

              {/* Vault lock/unlock */}
              <Button
                size="icon"
                variant={vaultIsOpen ? "secondary" : "outline"}
                className={`h-7 w-7 ${vaultIsOpen ? "border-emerald-500 bg-emerald-500/10" : ""}`}
                title={vaultIsOpen ? t("agent_editor.vault_locked") : t("agent_editor.vault_unlock")}
                onClick={async () => {
                  if (vaultIsOpen) return;
                  if (vaultState === "locked") {
                    setShowVaultUnlock(true);
                  } else {
                    setError(t("agent_editor.vault_not_unlocked"));
                  }
                }}
              >
                {vaultIsOpen ? (
                  <Unlock className="w-3.5 h-3.5 text-emerald-500" />
                ) : (
                  <Lock className="w-3.5 h-3.5" />
                )}
              </Button>
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

      <Tabs defaultValue="general" className="mb-6">
        <TabsList>
          <TabsTrigger value="general">{t("agent_editor.tab_general")}</TabsTrigger>
          <TabsTrigger value="dockerfile">{t("agent_editor.tab_dockerfile")}</TabsTrigger>
          <TabsTrigger value="roles">{t("agent_editor.tab_roles")}</TabsTrigger>
        </TabsList>

        <TabsContent value="general">
      {/* General */}
      <CollapsibleSection label={t("agent_editor.section_general")} defaultOpen={false}>
      <Card className="mb-0">
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
      </CollapsibleSection>

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
        {/* MCPs brick — spans 2 columns */}
        <CollapsibleSection
          label={`${t("agent_editor.section_mcps")} (${form.mcp_bindings.length} ${t("agent_editor.mcp_count_suffix")})`}
          defaultOpen={false}
        >
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-md bg-cyan-50 dark:bg-cyan-950/40 border border-cyan-100 dark:border-cyan-900/50 flex items-center justify-center">
                  <PlugZap className="w-4 h-4 text-cyan-600 dark:text-cyan-400" />
                </div>
                <div className="text-[14px] font-semibold text-foreground">
                  {form.mcp_bindings.length}{" "}
                  {t("agent_editor.mcp_count_suffix")}
                </div>
              </div>
              <Select
                value=""
                onValueChange={(mcpId) => {
                  if (!mcpId) return;
                  updateField("mcp_bindings", [
                    ...form.mcp_bindings,
                    { mcp_server_id: mcpId, parameters_override: {}, position: form.mcp_bindings.length },
                  ]);
                }}
              >
                <SelectTrigger className="w-auto gap-1.5 h-8 text-[12px]">
                  <Plus className="w-3.5 h-3.5" />
                  {t("agent_editor.mcp_add_short")}
                </SelectTrigger>
                <SelectContent>
                  {availableMCPs
                    .filter((m) => {
                      const hasParams = Array.isArray(m.parameters) && m.parameters.length > 0;
                      if (hasParams) return true;
                      return !form.mcp_bindings.some((b) => b.mcp_server_id === m.id);
                    })
                    .map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.name} ({m.transport})
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {!currentTarget && form.mcp_bindings.length > 0 && (
              <p className="text-amber-600 text-[12px] mb-2">
                ⚠ {t("agent_editor.mcp_no_target_warning")}
              </p>
            )}
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

                    {/* Runtime selector */}
                    <div className="mt-2">
                      <Label className="text-[11px]">
                        {t("agent_editor.mcp_runtime_label")}
                      </Label>
                      <select
                        className="text-[12px] border rounded px-2 py-1 bg-background w-full mt-1"
                        value={(b.parameters_override as Record<string, unknown>)?.runtime as string ?? ""}
                        onChange={(e) => {
                          const next = [...form.mcp_bindings];
                          const prev = (b.parameters_override ?? {}) as Record<string, unknown>;
                          next[idx] = {
                            ...b,
                            parameters_override: { ...prev, runtime: e.target.value },
                          };
                          updateField("mcp_bindings", next);
                        }}
                      >
                        <option value="">{currentTarget ? t("target.none") : t("agent_editor.mcp_no_target_warning")}</option>
                        {(((currentTarget as Record<string, unknown> | null)?.modes as Array<{ runtime: string }>) ?? []).map((m) => (
                          <option key={m.runtime} value={m.runtime}>{m.runtime}</option>
                        ))}
                      </select>
                    </div>

                    {/* Parameters form */}
                    {(mcpDetails(b.mcp_server_id)?.parameters ?? []).length > 0 && (
                      <div className="mt-2">
                        <Label className="text-[11px]">
                          {t("agent_editor.mcp_params_label")}
                        </Label>
                        {(mcpDetails(b.mcp_server_id)?.parameters ?? []).map((param) => (
                          <div key={param.name} className="flex items-center gap-2 mt-1">
                            <label
                              className="text-[11px] text-muted-foreground w-32 shrink-0 truncate"
                              title={param.description}
                            >
                              {param.name} {param.is_required && <span className="text-destructive">*</span>}
                            </label>
                            <input
                              type={param.is_secret ? "password" : "text"}
                              className="flex-1 text-[12px] border rounded px-2 py-1 bg-background font-mono"
                              placeholder={param.is_secret ? "${" + param.name + "}" : param.description}
                              value={
                                ((b.parameters_override as Record<string, unknown>)?.params as Record<string, string> ?? {})[param.name]
                                ?? (param.is_secret ? "${" + param.name + "}" : "")
                              }
                              onChange={(e) => {
                                const next = [...form.mcp_bindings];
                                const prev = (b.parameters_override ?? {}) as Record<string, unknown>;
                                const params = { ...((prev.params as Record<string, string>) ?? {}) };
                                params[param.name] = e.target.value;
                                next[idx] = {
                                  ...b,
                                  parameters_override: { ...prev, params },
                                };
                                updateField("mcp_bindings", next);
                              }}
                            />
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Preview — resolved template */}
                    {(b.parameters_override as Record<string, unknown>)?.runtime && currentTarget && (() => {
                      const overrideRuntime = (b.parameters_override as Record<string, unknown>).runtime as string;
                      const modes = (currentTarget as Record<string, unknown>).modes as Array<{ runtime: string; template: string; action_type: string; config_path?: string }> ?? [];
                      const mode = modes.find((m) => m.runtime === overrideRuntime);
                      if (!mode) return null;
                      const mcp = mcpDetails(b.mcp_server_id);
                      const params = ((b.parameters_override as Record<string, unknown>)?.params as Record<string, string>) ?? {};
                      let resolved = mode.template
                        .replace(/\{name\}/g, mcp?.name ?? "")
                        .replace(/\{package\}/g, mcp?.repo ?? mcp?.name ?? "");
                      const envEntries = Object.entries(params).filter(([, v]) => v);
                      if (mode.template.includes("{env_toml}")) {
                        const envToml = envEntries.length > 0
                          ? "\n[mcp_servers.env]\n" + envEntries.map(([k, v]) => `${k} = "${v}"`).join("\n")
                          : "";
                        resolved = resolved.replace(/\{env_toml\}/g, envToml);
                      }
                      if (mode.template.includes("{env_json}")) {
                        const envJson = envEntries.length > 0
                          ? ', "env": {' + envEntries.map(([k, v]) => `"${k}": "${v}"`).join(", ") + "}"
                          : "";
                        resolved = resolved.replace(/\{env_json\}/g, envJson);
                      }
                      return (
                        <details className="mt-2">
                          <summary className="text-[11px] text-muted-foreground cursor-pointer">
                            {t("agent_editor.mcp_preview_summary", { action: mode.action_type, path: mode.config_path ?? "install_mcp.sh" })}
                          </summary>
                          <pre className="text-[11px] font-mono bg-muted p-2 rounded mt-1 overflow-x-auto whitespace-pre-wrap">
                            {resolved}
                          </pre>
                        </details>
                      );
                    })()}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
        </CollapsibleSection>

        {/* Skills brick — spans 2 columns */}
        <CollapsibleSection
          label={`${t("agent_editor.section_skills")} (${form.skill_bindings.length} ${t("agent_editor.skill_count_suffix")})`}
          defaultOpen={false}
        >
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-md bg-amber-50 dark:bg-amber-950/40 border border-amber-100 dark:border-amber-900/50 flex items-center justify-center">
                  <BookMarked className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                </div>
                <div className="text-[14px] font-semibold text-foreground">
                  {form.skill_bindings.length}{" "}
                  {t("agent_editor.skill_count_suffix")}
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
        </CollapsibleSection>
      </div>

        </TabsContent>

        <TabsContent value="roles">
      {/* Role selection */}
      <Card className="mb-6">
        <CardContent className="pt-5">
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.section_role")}</Label>
            <Select
              value={form.role_id}
              onValueChange={(v) => updateField("role_id", v)}
            >
              <SelectTrigger>
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
          </div>
        </CardContent>
      </Card>

      {/* Profiles */}
      {!isNew && (
        <>
          <CollapsibleSection label={t("agent_editor.section_profiles")} defaultOpen={false}>
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
          </CollapsibleSection>
        </>
      )}

        </TabsContent>

        <TabsContent value="dockerfile">
      {/* Dockerfile selection */}
      <Card className="mb-6">
        <CardContent className="pt-5">
          <div className="flex flex-col gap-1.5">
            <Label>{t("agent_editor.section_dockerfile")}</Label>
            <Select
              value={form.dockerfile_id}
              onValueChange={(v) => updateField("dockerfile_id", v)}
            >
              <SelectTrigger>
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
          </div>
        </CardContent>
      </Card>

      {/* Env vars from Dockerfile.json + overrides */}
      <CollapsibleSection label={t("agent_editor.section_env")} defaultOpen={false}>
      <Card className="mb-0">
        <CardContent className="pt-5 space-y-2">
          {dockerfileEnvKeys.length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic">
              {t("agent_editor.env_no_dockerfile")}
            </p>
          ) : (
            dockerfileEnvKeys.map((key) => {
              const baseValue = (() => {
                try {
                  const files = dockerfileDetailQuery.data?.files ?? [];
                  const pf = files.find((f) => f.path === "Dockerfile.json");
                  if (!pf) return "";
                  const parsed = JSON.parse(pf.content);
                  return String((parsed?.docker?.Environments ?? {})[key] ?? "");
                } catch { return ""; }
              })();
              const override = form.env_overrides[key];
              const isOverridden = override?.value !== undefined;
              const isExcluded = override?.excluded ?? false;
              const displayValue = isOverridden ? (override.value ?? "") : baseValue;
              const secretRef = extractSecretName(displayValue) ?? (displayValue.startsWith("$") && displayValue.length > 1 ? displayValue.slice(1) : null);

              return (
                <div key={key} className={`flex items-center gap-2 ${isExcluded ? "opacity-40" : ""}`}>
                  <input
                    type="checkbox"
                    checked={isExcluded}
                    onChange={(e) => {
                      setEnvOverride(key, {
                        ...override,
                        excluded: e.target.checked,
                      });
                    }}
                    title={t("agent_editor.env_exclude")}
                    className="h-3.5 w-3.5 accent-primary shrink-0"
                  />
                  <span className="font-mono text-[12px] text-muted-foreground w-44 shrink-0 truncate" title={key}>
                    {key}
                  </span>
                  <Input
                    value={displayValue}
                    onChange={(e) => {
                      setEnvOverride(key, {
                        ...override,
                        value: e.target.value,
                      });
                    }}
                    disabled={isExcluded}
                    className={`flex-1 min-w-[180px] font-mono text-[12px] ${isOverridden ? "border-amber-500/50" : ""}`}
                  />
                  {secretRef && !isExcluded && (
                    <EnvVarStatus
                      name={secretRef}
                      status={vaultSecretStatus[secretRef]}
                      compact
                    />
                  )}
                  {isOverridden && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 shrink-0"
                      onClick={() => {
                        const next = { ...override };
                        delete next.value;
                        if (!next.excluded) {
                          setEnvOverride(key, undefined);
                        } else {
                          setEnvOverride(key, next);
                        }
                      }}
                      title={t("agent_editor.env_reset")}
                    >
                      <X className="w-3.5 h-3.5 text-amber-500" />
                    </Button>
                  )}
                </div>
              );
            })
          )}
          {!decryptedSecrets && (
            <p className="text-[11px] text-muted-foreground italic mt-2">
              {t("agent_editor.vault_hint")}
            </p>
          )}
        </CardContent>
      </Card>

      </CollapsibleSection>

      {/* Mounts from Dockerfile.json + overrides */}
      <CollapsibleSection label={t("agent_editor.section_mounts")} defaultOpen={false}>
      <Card className="mb-0">
        <CardContent className="pt-5 space-y-2">
          {dockerfileMounts.length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic">
              {t("agent_editor.env_no_dockerfile")}
            </p>
          ) : (
            dockerfileMounts.map((mount) => {
              const override = form.mount_overrides[mount.target];
              const isOverridden = override?.source !== undefined;
              const isExcluded = override?.excluded ?? false;
              const displaySource = isOverridden ? (override.source ?? "") : mount.source;
              return (
                <div key={mount.target} className={`flex items-center gap-2 ${isExcluded ? "opacity-40" : ""}`}>
                  <input
                    type="checkbox"
                    checked={isExcluded}
                    onChange={(e) => setMountOverride(mount.target, { ...override, excluded: e.target.checked })}
                    className="h-3.5 w-3.5 accent-primary shrink-0"
                  />
                  <span className="font-mono text-[11px] text-muted-foreground w-40 shrink-0 truncate" title={mount.target}>
                    {mount.target}
                  </span>
                  <Input
                    value={displaySource}
                    onChange={(e) => setMountOverride(mount.target, { ...override, source: e.target.value })}
                    disabled={isExcluded}
                    className={`flex-1 min-w-[150px] font-mono text-[12px] ${isOverridden ? "border-amber-500/50" : ""}`}
                  />
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    {mount.readonly ? "ro" : "rw"}
                  </span>
                  {isOverridden && (
                    <Button
                      variant="ghost" size="icon" className="h-7 w-7 shrink-0"
                      onClick={() => {
                        const next = { ...override };
                        delete next.source;
                        if (!next.excluded) setMountOverride(mount.target, undefined);
                        else setMountOverride(mount.target, next);
                      }}
                      title={t("agent_editor.env_reset")}
                    >
                      <X className="w-3.5 h-3.5 text-amber-500" />
                    </Button>
                  )}
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      </CollapsibleSection>

      {/* Params from Dockerfile.json + overrides */}
      <CollapsibleSection label={t("agent_editor.section_params")} defaultOpen={false}>
      <Card className="mb-0">
        <CardContent className="pt-5 space-y-2">
          {Object.keys(dockerfileParams).length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic">
              {t("agent_editor.env_no_dockerfile")}
            </p>
          ) : (
            Object.entries(dockerfileParams).map(([key, baseValue]) => {
              const override = form.param_overrides[key];
              const isOverridden = override?.value !== undefined;
              const isExcluded = override?.excluded ?? false;
              const displayValue = isOverridden ? (override.value ?? "") : baseValue;
              return (
                <div key={key} className={`flex items-center gap-2 ${isExcluded ? "opacity-40" : ""}`}>
                  <input
                    type="checkbox"
                    checked={isExcluded}
                    onChange={(e) => setParamOverride(key, { ...override, excluded: e.target.checked })}
                    className="h-3.5 w-3.5 accent-primary shrink-0"
                  />
                  <span className="font-mono text-[12px] text-muted-foreground w-44 shrink-0 truncate" title={key}>
                    {key}
                  </span>
                  <Input
                    value={displayValue}
                    onChange={(e) => setParamOverride(key, { ...override, value: e.target.value })}
                    disabled={isExcluded}
                    className={`flex-1 min-w-[180px] font-mono text-[12px] ${isOverridden ? "border-amber-500/50" : ""}`}
                  />
                  {isOverridden && (
                    <Button
                      variant="ghost" size="icon" className="h-7 w-7 shrink-0"
                      onClick={() => {
                        const next = { ...override };
                        delete next.value;
                        if (!next.excluded) setParamOverride(key, undefined);
                        else setParamOverride(key, next);
                      }}
                      title={t("agent_editor.env_reset")}
                    >
                      <X className="w-3.5 h-3.5 text-amber-500" />
                    </Button>
                  )}
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      </CollapsibleSection>

      {/* Lifecycle */}
      <CollapsibleSection label={t("agent_editor.section_lifecycle")} defaultOpen={false}>
      <Card className="mb-0">
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
      </CollapsibleSection>

        </TabsContent>
      </Tabs>

      {/* Generated files explorer */}
      {!isNew && generatedFiles.length > 0 && (
        <>
          <CollapsibleSection label={t("agent_editor.section_generated")}>
          <Card className="mb-6">
            <CardContent className="pt-5">
              <div className="flex gap-4 min-h-[400px]">
                <div className="w-48 shrink-0 border-r pr-3 overflow-y-auto max-h-[800px]">
                  <FileTree
                    files={generatedFiles.map((f) => ({
                      id: f.path,
                      path: f.path,
                      type: f.type,
                    }))}
                    selectedId={selectedGenFile}
                    onSelect={(id) => setSelectedGenFile(id)}
                  />
                </div>
                <div className="flex-1 min-w-0 overflow-auto">
                  {selectedGenFile ? (
                    <CodeEditor
                      value={(() => {
                        const raw = generatedFiles.find((f) => f.path === selectedGenFile)?.content ?? "";
                        return selectedGenFile === ".env" ? maskEnvSecrets(raw) : raw;
                      })()}
                      onChange={() => {}}
                      readOnly
                      path={selectedGenFile}
                      minHeight={400}
                      fill
                    />
                  ) : (
                    <p className="text-[12px] text-muted-foreground italic p-3">
                      {t("agent_editor.generated_select_file")}
                    </p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
          </CollapsibleSection>
        </>
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
        <DialogContent className="sm:max-w-3xl sm:max-h-[85vh] overflow-y-auto">
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
                {preview.env_file ? maskEnvSecrets(preview.env_file) : "(empty)"}
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
          secrets={decryptedSecrets ?? undefined}
          dockerfileJsonContent={dockerfileJsonContentForLaunch}
        />
      )}

      <ConfirmDialog
        open={launchPendingSecrets !== null}
        onOpenChange={(open) => {
          if (!open) setLaunchPendingSecrets(null);
        }}
        title={t("launch_warning.title")}
        description={t("launch_warning.description", {
          keys: launchEmptyKeys.join(", "),
        })}
        confirmLabel={t("launch_warning.confirm")}
        cancelLabel={t("launch_warning.cancel")}
        onConfirm={async () => {
          if (!form.dockerfile_id || !launchPendingSecrets) return;
          const c = await containersApi.run(
            form.dockerfile_id,
            launchPendingSecrets,
          );
          setRunningContainerId(c.id);
          setLaunchPendingSecrets(null);
        }}
      />

      {terminalContainer && (
        <TerminalWindow
          containerId={terminalContainer.id}
          containerName={terminalContainer.name}
          onClose={() => setTerminalContainer(null)}
        />
      )}
      <VaultUnlockDialog
        open={showVaultUnlock}
        email="admin@agflow.example.com"
        onComplete={async () => {
          setShowVaultUnlock(false);
          const s = await decryptUserSecrets();
          if (Object.keys(s).length > 0) setDecryptedSecrets(s);
        }}
        onClose={() => setShowVaultUnlock(false)}
      />
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


function CollapsibleSection({
  label,
  defaultOpen = true,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mb-6">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-3 hover:text-foreground transition-colors"
      >
        <ChevronRight className={cn("w-3 h-3 transition-transform", open && "rotate-90")} />
        {label}
      </button>
      {open && children}
    </div>
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
