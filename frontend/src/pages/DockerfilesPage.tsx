import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Crosshair,
  Download,
  FilePlus,
  FolderPlus,
  Hammer,
  Lock,
  MessageSquare,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Square,
  ScrollText,
  TerminalSquare,
  Trash2,
  Unlock,
  Upload,
} from "lucide-react";
import {
  useDockerfileDetail,
  useDockerfiles,
} from "@/hooks/useDockerfiles";
import { useDiscoveryServices } from "@/hooks/useCatalogs";
import { TargetSelectorDialog } from "@/components/TargetSelectorDialog";
import type { TargetSummary } from "@/lib/catalogsApi";
import { useContainers } from "@/hooks/useContainers";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import { BuildModal } from "@/components/BuildModal";
import { CodeEditor } from "@/components/CodeEditor";
import { FileTree } from "@/components/FileTree";
import { useVault } from "@/hooks/useVault";
import { useEmptyLaunchKeys } from "@/hooks/useEmptyLaunchKeys";
import { userSecretsApi } from "@/lib/userSecretsApi";
import { TerminalWindow } from "@/components/TerminalWindow";
import { LogsWindow } from "@/components/LogsWindow";
import { DockerChatModal } from "@/components/DockerChatModal";
import { DockerfileParamsDialog } from "@/components/DockerfileParamsDialog";
import { ChatWindow } from "@/components/ChatWindow";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { VaultUnlockDialog } from "@/components/VaultUnlockDialog";
import { PromptDialog } from "@/components/PromptDialog";
import { dockerfilesApi } from "@/lib/dockerfilesApi";
import { cn, maskEnvSecrets } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Visible files that cannot be deleted — mirrors backend PROTECTED_FILES,
// minus Dockerfile.json which is hidden from the UI entirely.
const PROTECTED_FILES: readonly string[] = [
  "Dockerfile",
  "entrypoint.sh",
  "description.md",
];

// Files that are system-managed (seeded + protected) but hidden from the
// file list sidebar. Dockerfile.json holds the default parameters and is
// edited via the dedicated "Paramètres" dialog, not inline.
const HIDDEN_FILES: readonly string[] = ["Dockerfile.json"];

export function DockerfilesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { state: vaultState, decryptSecret } = useVault();
  const {
    dockerfiles,
    isLoading,
    createMutation,
    deleteMutation,
    createFileMutation,
    updateFileMutation,
    deleteFileMutation,
  } = useDockerfiles();
  const {
    containers,
    runMutation: runContainerMutation,
    stopMutation: stopContainerMutation,
  } = useContainers();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [draftContent, setDraftContent] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showAddFileDialog, setShowAddFileDialog] = useState(false);
  const [addFilePrefix, setAddFilePrefix] = useState("");
  const [sidebarWidth, setSidebarWidth] = useState(220);
  const [deleteFolderPath, setDeleteFolderPath] = useState<string | null>(null);
  const [showParamsDialog, setShowParamsDialog] = useState(false);
  const [showDeleteDockerfileConfirm, setShowDeleteDockerfileConfirm] =
    useState(false);
  const [showDeleteFileConfirm, setShowDeleteFileConfirm] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [actionErrors, setActionErrors] = useState<string[]>([]);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [chatOpenFor, setChatOpenFor] = useState<string | null>(null);
  const [regenSpin, setRegenSpin] = useState(false);
  const [decryptedSecrets, setDecryptedSecrets] = useState<Record<string, string> | null>(null);
  const [showVaultUnlock, setShowVaultUnlock] = useState(false);
  const [logsContainer, setLogsContainer] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [terminalContainer, setTerminalContainer] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [pendingNavigation, setPendingNavigation] = useState<
    (() => void) | null
  >(null);
  const { services: discoveryServices } = useDiscoveryServices();
  const [showTargetDialog, setShowTargetDialog] = useState(false);
  const hasUnsavedChanges = draftContent !== null;
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

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (hasUnsavedChanges) handleSaveFile();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const detail = useDockerfileDetail(selectedId);
  const currentDockerfile = detail.data?.dockerfile ?? null;
  const allFiles = detail.data?.files ?? [];
  const files = allFiles.filter((f) => !HIDDEN_FILES.includes(f.path));
  const dockerfileJsonFile =
    allFiles.find((f) => f.path === "Dockerfile.json") ?? null;
  const currentTarget: TargetSummary | null = (() => {
    if (!dockerfileJsonFile) return null;
    try {
      const parsed = JSON.parse(dockerfileJsonFile.content);
      return parsed.Target ?? null;
    } catch {
      return null;
    }
  })();
  const { emptyKeys: launchEmptyKeys } = useEmptyLaunchKeys({
    dockerfileJsonContent: dockerfileJsonFile?.content ?? null,
    decryptedSecrets,
  });
  const [launchPendingSecrets, setLaunchPendingSecrets] = useState<
    Record<string, string> | null
  >(null);
  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;

  async function handleCreate(values: Record<string, string>) {
    const created = await createMutation.mutateAsync({
      id: values.id ?? "",
      display_name: values.display_name ?? "",
    });
    setSelectedId(created.id);
  }

  async function handleAcceptGenerated(
    dockerfileId: string,
    displayName: string,
    generated: {
      dockerfile: string;
      entrypoint_sh: string;
    },
  ) {
    await createMutation.mutateAsync({
      id: dockerfileId,
      display_name: displayName,
    });
    const fresh = await dockerfilesApi.get(dockerfileId);
    const fillStandardFile = async (path: string, content: string) => {
      const file = fresh.files.find((f) => f.path === path);
      if (file) {
        await dockerfilesApi.updateFile(dockerfileId, file.id, content);
      }
    };
    await fillStandardFile("Dockerfile", generated.dockerfile);
    await fillStandardFile("entrypoint.sh", generated.entrypoint_sh);
    setSelectedId(dockerfileId);
  }

  async function handleDelete() {
    if (!selectedId) return;
    await deleteMutation.mutateAsync(selectedId);
    setSelectedId(null);
    setSelectedFileId(null);
    setDraftContent(null);
  }

  async function handleAddFile(values: Record<string, string>) {
    if (!selectedId) return;
    const path = values.path ?? "";
    const f = await createFileMutation.mutateAsync({
      dockerfileId: selectedId,
      payload: { path, content: "" },
    });
    setSelectedFileId(f.id);
    setDraftContent(null);
  }

  async function handleSaveFile() {
    if (!selectedId || !selectedFile || draftContent === null) return;
    await updateFileMutation.mutateAsync({
      dockerfileId: selectedId,
      fileId: selectedFile.id,
      content: draftContent,
    });
    setDraftContent(null);
  }

  async function handleSelectTarget(target: TargetSummary) {
    if (!dockerfileJsonFile || !selectedId) return;
    try {
      const parsed = JSON.parse(dockerfileJsonFile.content);
      parsed.Target = {
        id: target.id,
        name: target.name,
        description: target.description,
        modes: target.modes,
      };

      // Auto-add Mount for insert_in_file config_path
      const insertMode = target.modes.find(
        (m: { action_type: string; config_path?: string }) =>
          m.action_type === "insert_in_file" && m.config_path,
      );
      if (insertMode?.config_path) {
        const configPath: string = insertMode.config_path;
        // "~/.vibe/config.toml" → source = "config.toml", target = "~/.vibe/config.toml"
        const lastSlash = configPath.lastIndexOf("/");
        const source = lastSlash >= 0 ? configPath.slice(lastSlash + 1) : configPath;
        const mounts: Array<{ source: string; target: string; readonly: boolean }> =
          parsed.docker?.Mounts ?? [];
        // Only add if no mount with this target already exists
        if (!mounts.some((m) => m.target === configPath)) {
          mounts.push({ source, target: configPath, readonly: false });
          if (!parsed.docker) parsed.docker = {};
          parsed.docker.Mounts = mounts;
        }
      }

      await updateFileMutation.mutateAsync({
        dockerfileId: selectedId,
        fileId: dockerfileJsonFile.id,
        content: JSON.stringify(parsed, null, 2),
      });
    } catch {
      // JSON parse error — ignore
    }
  }

  async function handleDeleteFile() {
    if (!selectedId || !selectedFile) return;
    await deleteFileMutation.mutateAsync({
      dockerfileId: selectedId,
      fileId: selectedFile.id,
    });
    setSelectedFileId(null);
    setDraftContent(null);
  }

  // ─────────────────────────────────────────────────────────
  // Unsaved-changes guard: if the file editor holds a draft,
  // intercept in-page selection changes AND SPA link clicks to
  // ask the user whether to save, discard or cancel.
  // ─────────────────────────────────────────────────────────
  function guardedNavigate(action: () => void) {
    if (hasUnsavedChanges) {
      setPendingNavigation(() => action);
    } else {
      action();
    }
  }

  async function handleSaveAndContinue() {
    await handleSaveFile();
    const action = pendingNavigation;
    setPendingNavigation(null);
    action?.();
  }

  function handleDiscardAndContinue() {
    setDraftContent(null);
    const action = pendingNavigation;
    setPendingNavigation(null);
    action?.();
  }

  function handleCancelNavigation() {
    setPendingNavigation(null);
  }

  // Catch browser-level nav (refresh, tab close) when a draft is pending.
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  // Catch SPA nav (clicks on NavLink in the sidebar menu). We only need
  // this when there are unsaved changes; it captures the click before the
  // router handles it and stores a deferred navigate(href) action.
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const anchor = (e.target as HTMLElement | null)?.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.target === "_blank") return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("http")) return;
      // Same location? let it through.
      if (href === window.location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      setPendingNavigation(() => () => navigate(href));
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [hasUnsavedChanges, navigate]);

  function reportError(err: unknown) {
    const resp = (err as { response?: { data?: { detail?: unknown } } })
      .response;
    const detail = resp?.data?.detail;
    let messages: string[];
    if (typeof detail === "string") {
      messages = [detail];
    } else if (
      detail &&
      typeof detail === "object" &&
      "errors" in detail &&
      Array.isArray((detail as { errors: unknown[] }).errors)
    ) {
      messages = (detail as { errors: string[] }).errors;
    } else {
      const fallback =
        (err as { message?: string }).message ??
        t("dockerfiles.import.error_unknown");
      messages = [fallback];
    }
    setActionErrors(messages);
  }

  async function handleBuild() {
    if (!selectedId) return;
    try {
      const res = await dockerfilesApi.build(selectedId);
      setBuildId(res.id);
    } catch (err) {
      reportError(err);
    }
  }

  async function decryptUserSecrets(): Promise<Record<string, string>> {
    if (vaultState !== "unlocked") return {};
    try {
      const secrets = await userSecretsApi.list();
      const result: Record<string, string> = {};
      for (const s of secrets) {
        try {
          result[s.name] = decryptSecret(s.ciphertext, s.iv);
        } catch {
          // Skip secrets that fail to decrypt
        }
      }
      return result;
    } catch {
      return {};
    }
  }

  async function handleRunContainer() {
    if (!selectedId) return;
    try {
      // Merge: vault secrets + test overrides from Dockerfile.json
      const vaultSecrets = decryptedSecrets ?? await decryptUserSecrets();
      const testOverrides: Record<string, string> = {};
      if (dockerfileJsonFile) {
        try {
          const parsed = JSON.parse(dockerfileJsonFile.content);
          const to = parsed?.TestOverrides ?? {};
          for (const [k, v] of Object.entries(to)) {
            if (typeof v === "string") testOverrides[k] = v;
          }
        } catch { /* ignore */ }
      }
      const secrets = { ...vaultSecrets, ...testOverrides };
      if (launchEmptyKeys.length > 0) {
        setLaunchPendingSecrets(secrets);
        return;
      }
      await runContainerMutation.mutateAsync({
        dockerfileId: selectedId,
        secrets,
      });
    } catch {
      // Error handled by mutation state
    }
  }

  async function confirmRunContainer() {
    if (!selectedId || !launchPendingSecrets) return;
    await runContainerMutation.mutateAsync({
      dockerfileId: selectedId,
      secrets: launchPendingSecrets,
    });
    setLaunchPendingSecrets(null);
  }

  async function handleStopContainer(containerId: string) {
    try {
      await stopContainerMutation.mutateAsync(containerId);
    } catch (err) {
      reportError(err);
    }
  }

  const handleSidebarDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = sidebarWidth;
      const onMove = (ev: MouseEvent) => {
        const newW = Math.max(150, Math.min(500, startW + ev.clientX - startX));
        setSidebarWidth(newW);
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [sidebarWidth],
  );

  async function handleExport() {
    if (!selectedId) return;
    try {
      const blob = await dockerfilesApi.exportZip(selectedId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedId}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      reportError(err);
    }
  }

  function handleImportClick() {
    importInputRef.current?.click();
  }

  function handleImportFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    e.target.value = ""; // allow picking the same file twice
    if (picked) setImportFile(picked);
  }

  async function handleImportConfirm() {
    if (!selectedId || !importFile) return;
    setActionErrors([]);
    try {
      await dockerfilesApi.importZip(selectedId, importFile);
      setImportFile(null);
      setSelectedFileId(null);
      setDraftContent(null);
      qc.invalidateQueries({ queryKey: ["dockerfile", selectedId] });
    } catch (err: unknown) {
      reportError(err);
      setImportFile(null);
      throw err;
    }
  }

  if (isLoading)
    return <p className="p-6 text-muted-foreground">{t("secrets.loading")}</p>;

  const isProtected =
    selectedFile !== null && PROTECTED_FILES.includes(selectedFile.path);

  return (
    <div className="flex flex-col h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Header row: dropdown + action buttons */}
      <div className="flex flex-wrap items-center gap-2 md:gap-3 px-4 py-2.5 border-b bg-muted/30 shrink-0">
        {/* Dropdown to pick a dockerfile */}
        <Select
          value={selectedId ?? ""}
          onValueChange={(value) =>
            guardedNavigate(() => {
              setSelectedId(value || null);
              setSelectedFileId(null);
              setDraftContent(null);
            })
          }
        >
          <SelectTrigger className="w-40 md:w-56">
            <SelectValue placeholder={t("dockerfiles.select_dockerfile")} />
          </SelectTrigger>
          <SelectContent>
            {(dockerfiles ?? []).map((d) => (
              <SelectItem key={d.id} value={d.id}>
                <span className="flex items-center gap-2">
                  <span className="truncate">{d.display_name}</span>
                  <BuildStatusBadge status={d.display_status} />
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={() => setShowCreateDialog(true)}
            title={t("dockerfiles.add_button")}
          >
            <Plus className="w-3.5 h-3.5" />
          </Button>
        </div>

        {selectedId && currentDockerfile && (
          <>
            <div className="w-px h-5 bg-border shrink-0" />

            {/* Config & transfer — icon-only with tooltips */}
            <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => setShowTargetDialog(true)}
                disabled={!dockerfileJsonFile || !discoveryServices?.length}
                title={t("target.select_button")}
              >
                <Crosshair className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => setShowParamsDialog(true)}
                disabled={!dockerfileJsonFile}
                title={t("dockerfiles.params_button")}
              >
                <Settings2 className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleExport}
                title={t("dockerfiles.export_button")}
              >
                <Download className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleImportClick}
                title={t("dockerfiles.import_button")}
              >
                <Upload className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 active:scale-100 active:translate-y-0 active:shadow-none"
                onClick={async () => {
                  if (!selectedId) return;
                  setRegenSpin(true);
                  window.setTimeout(() => setRegenSpin(false), 1400);
                  const secrets = decryptedSecrets ?? await decryptUserSecrets();
                  await dockerfilesApi.regenerateTmp(selectedId, secrets);
                  qc.invalidateQueries({ queryKey: ["dockerfile", selectedId] });
                }}
                title={t("dockerfiles.regenerate_tmp_button")}
              >
                <RefreshCw
                  className="w-3.5 h-3.5"
                  style={regenSpin ? { animation: "spin 0.7s linear 2" } : undefined}
                />
              </Button>
            </div>

            {currentTarget ? (
              <Badge
                variant="outline"
                className="text-[11px] font-mono cursor-pointer hover:bg-secondary transition-colors"
                onClick={() => setShowTargetDialog(true)}
                title={t("target.select_button")}
              >
                {currentTarget.name}
              </Badge>
            ) : (
              <Badge
                variant="secondary"
                className="text-[11px] cursor-pointer hover:bg-secondary/80 transition-colors"
                onClick={() => setShowTargetDialog(true)}
                title={t("target.select_button")}
              >
                {t("target.none")}
              </Badge>
            )}

            <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleBuild}
                title={t("dockerfiles.build_button")}
              >
                <Hammer className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleRunContainer}
                disabled={
                  currentDockerfile.display_status !== "up_to_date" ||
                  runContainerMutation.isPending
                }
                title={t("dockerfiles.run_button")}
              >
                <Play className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => setChatOpenFor(selectedId)}
                disabled={currentDockerfile.display_status !== "up_to_date"}
                title={t("dockerfiles.chat_window_button")}
              >
                <MessageSquare className="w-3.5 h-3.5" />
              </Button>
            </div>
            <Button
              size="icon"
              variant="outline"
              className={`h-7 w-7 ${vaultIsOpen ? "border-emerald-500 bg-emerald-500/10" : ""}`}
              title={vaultIsOpen ? t("dockerfiles.vault_unlocked") : t("dockerfiles.vault_unlock")}
              onClick={async () => {
                if (vaultIsOpen) return;
                if (vaultState === "locked") {
                  setShowVaultUnlock(true);
                } else {
                  navigate("/my-secrets");
                }
              }}
            >
              {vaultIsOpen ? (
                <Unlock className="w-3.5 h-3.5 text-emerald-500" />
              ) : (
                <Lock className="w-3.5 h-3.5" />
              )}
            </Button>
            <input
              ref={importInputRef}
              type="file"
              accept=".zip,application/zip"
              onChange={handleImportFilePicked}
              className="hidden"
            />
          </>
        )}
      </div>

      {/* Body: sidebar + editor */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {selectedId && currentDockerfile ? (
          <>
            {/* Left sidebar: file list + running instances + delete */}
            <aside
              style={{ width: `${sidebarWidth}px` }}
              className="hidden md:flex shrink-0 border-r flex-col overflow-hidden"
            >
              <div className="p-3 border-b flex items-center justify-between">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {t("dockerfiles.files_title")}
                </span>
                <div className="flex gap-0.5">
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    onClick={() => { setAddFilePrefix(""); setShowAddFileDialog(true); }}
                    title={t("dockerfiles.new_file_button")}
                  >
                    <FilePlus className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    onClick={() => { setAddFilePrefix(""); setShowAddFileDialog(true); }}
                    title={t("dockerfiles.new_folder_button")}
                  >
                    <FolderPlus className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-2">
                {files.length === 0 ? (
                  <p className="text-muted-foreground text-[12px] italic px-2 py-2">
                    {t("dockerfiles.no_files")}
                  </p>
                ) : (
                  <FileTree
                    files={files}
                    selectedId={selectedFileId}
                    protectedFiles={PROTECTED_FILES}
                    onSelect={(id) =>
                      guardedNavigate(() => {
                        setSelectedFileId(id);
                        setDraftContent(null);
                      })
                    }
                    onAddFileInFolder={(folder) => {
                      setAddFilePrefix(folder + "/");
                      setShowAddFileDialog(true);
                    }}
                    onDeleteFolder={(folder) => setDeleteFolderPath(folder)}
                    onDeleteFile={(id) => {
                      setSelectedFileId(id);
                      setDraftContent(null);
                      setShowDeleteFileConfirm(true);
                    }}
                  />
                )}
              </div>

              {/* Running instances */}
              {containers.length > 0 && (
                <div className="border-t">
                  <div className="px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                    {t("dockerfiles.running_instances")}
                  </div>
                  <ul className="px-2 pb-2 space-y-1 max-h-40 overflow-y-auto">
                    {containers.map((c) => (
                      <li
                        key={c.id}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-secondary/60"
                      >
                        <span
                          className={cn(
                            "w-1.5 h-1.5 rounded-full shrink-0",
                            c.status === "running"
                              ? "bg-emerald-500"
                              : c.status === "exited" || c.status === "dead"
                                ? "bg-zinc-500"
                                : "bg-amber-400",
                          )}
                          title={c.status}
                        />
                        <div className="min-w-0 flex-1">
                          <div
                            className="text-[11px] font-mono truncate"
                            title={c.name}
                          >
                            {c.name}
                          </div>
                          <div className="text-[10px] text-muted-foreground truncate">
                            {c.dockerfile_id}
                          </div>
                        </div>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 shrink-0"
                          onClick={() => setLogsContainer({ id: c.id, name: c.name })}
                          title="Logs"
                        >
                          <ScrollText className="w-3 h-3" />
                        </Button>
                        {c.status === "running" && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6 shrink-0"
                            onClick={() => setTerminalContainer({ id: c.id, name: c.name })}
                            title="Terminal"
                          >
                            <TerminalSquare className="w-3 h-3" />
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 shrink-0"
                          onClick={() => handleStopContainer(c.id)}
                          disabled={stopContainerMutation.isPending}
                          aria-label={t("dockerfiles.stop_instance")}
                          title={t("dockerfiles.stop_instance")}
                        >
                          <Square className="w-3 h-3 text-destructive" />
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Delete dockerfile */}
              <div className="p-3 border-t">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowDeleteDockerfileConfirm(true)}
                  className="w-full text-destructive"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  {t("dockerfiles.delete_button")}
                </Button>
              </div>
            </aside>

            {/* Resizable drag handle (desktop only) */}
            <div
              className="hidden md:block w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors shrink-0"
              onMouseDown={handleSidebarDragStart}
            />

            {/* Right: editor */}
            <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
              {/* File info bar */}
              <div className="flex items-center justify-between gap-3 px-4 py-2 border-b bg-muted/20 shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  {/* Mobile-only file picker */}
                  <Select
                    value={selectedFileId ?? ""}
                    onValueChange={(v) => {
                      if (v) { setSelectedFileId(v); setDraftContent(null); }
                    }}
                  >
                    <SelectTrigger className="md:hidden w-32 h-7 text-[11px]">
                      <SelectValue placeholder={t("dockerfiles.files_title")} />
                    </SelectTrigger>
                    <SelectContent>
                      {files.map((f) => (
                        <SelectItem key={f.id} value={f.id}>
                          <span className="font-mono text-[11px]">{f.path}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <BuildStatusBadge status={currentDockerfile.display_status} />
                  <span className="hidden md:inline text-[11px] text-muted-foreground">
                    {t("dockerfiles.current_hash")}:{" "}
                    <code className="font-mono">
                      {currentDockerfile.current_hash}
                    </code>
                  </span>
                </div>
              </div>

              {selectedFile ? (
                <div className="flex-1 flex flex-col min-h-0 px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <code className="font-mono text-[13px] font-semibold">
                        {selectedFile.path}
                      </code>
                      {isProtected && (
                        <Badge variant="secondary">
                          {t("dockerfiles.standard_file")}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {draftContent !== null && (
                        <Button size="sm" onClick={handleSaveFile}>
                          <Save className="w-3.5 h-3.5" />
                          {t("dockerfiles.save_button")}
                        </Button>
                      )}
                      {!isProtected && (
                        <Button
                          size="icon"
                          variant="ghost"
                          onClick={() => setShowDeleteFileConfirm(true)}
                          aria-label={t("dockerfiles.delete_button")}
                        >
                          <Trash2 className="w-3.5 h-3.5 text-destructive" />
                        </Button>
                      )}
                    </div>
                  </div>
                  <CodeEditor
                    value={
                      draftContent ??
                      (selectedFile.path === ".tmp/.env"
                        ? maskEnvSecrets(selectedFile.content)
                        : selectedFile.content)
                    }
                    onChange={(v) => setDraftContent(v)}
                    path={selectedFile.path}
                    fill
                  />
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted-foreground text-[13px] italic p-6">
                  {t("dockerfiles.pick_file_hint")}
                </div>
              )}
            </main>
          </>
        ) : (
          <main className="flex-1 flex items-center justify-center text-muted-foreground text-[13px] italic">
            {t("dockerfiles.select_dockerfile")}
          </main>
        )}
      </div>

      {showChat && (
        <DockerChatModal
          onClose={() => setShowChat(false)}
          onAccept={handleAcceptGenerated}
        />
      )}

      {buildId && selectedId && currentDockerfile && (
        <BuildModal
          dockerfileId={selectedId}
          dockerfileName={currentDockerfile.display_name}
          buildId={buildId}
          onClose={() => {
            setBuildId(null);
            qc.invalidateQueries({ queryKey: ["dockerfile", selectedId] });
          }}
        />
      )}

      <PromptDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        title={t("dockerfiles.new_dockerfile_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleCreate}
        fields={[
          {
            name: "display_name",
            label: t("dockerfiles.new_dockerfile_name_prompt"),
          },
          {
            name: "id",
            label: t("dockerfiles.new_dockerfile_id_prompt"),
            autoSlugFrom: "display_name",
            monospace: true,
          },
        ]}
      />

      <PromptDialog
        open={showAddFileDialog}
        onOpenChange={setShowAddFileDialog}
        title={t("dockerfiles.new_file_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleAddFile}
        fields={[
          {
            name: "path",
            label: t("dockerfiles.new_file_prompt"),
            placeholder: "config/settings.json",
            defaultValue: addFilePrefix,
            monospace: true,
          },
        ]}
      />

      {selectedId && (
        <DockerfileParamsDialog
          open={showParamsDialog}
          onOpenChange={setShowParamsDialog}
          dockerfileId={selectedId}
          file={dockerfileJsonFile}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["dockerfile", selectedId] });
          }}
        />
      )}

      {showTargetDialog && discoveryServices?.[0] && (
        <TargetSelectorDialog
          serviceId={discoveryServices[0].id}
          currentTargetName={currentTarget?.name}
          onSelect={handleSelectTarget}
          onClose={() => setShowTargetDialog(false)}
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
        onConfirm={confirmRunContainer}
      />

      <ConfirmDialog
        open={showDeleteDockerfileConfirm}
        onOpenChange={setShowDeleteDockerfileConfirm}
        title={t("dockerfiles.confirm_delete_title")}
        description={t("dockerfiles.confirm_delete_message", {
          name: currentDockerfile?.display_name ?? selectedId ?? "",
        })}
        confirmLabel={t("dockerfiles.confirm_delete_button")}
        destructive
        onConfirm={handleDelete}
      />

      <ConfirmDialog
        open={showDeleteFileConfirm}
        onOpenChange={setShowDeleteFileConfirm}
        title={t("dockerfiles.confirm_delete_file_title")}
        description={t("dockerfiles.confirm_delete_file_message", {
          path: selectedFile?.path ?? "",
        })}
        confirmLabel={t("dockerfiles.confirm_delete_button")}
        destructive
        onConfirm={handleDeleteFile}
      />

      <ConfirmDialog
        open={deleteFolderPath !== null}
        onOpenChange={(open) => { if (!open) setDeleteFolderPath(null); }}
        title={t("dockerfiles.confirm_delete_folder_title")}
        description={t("dockerfiles.confirm_delete_folder_message", {
          folder: deleteFolderPath ?? "",
        })}
        confirmLabel={t("dockerfiles.confirm_delete_button")}
        destructive
        onConfirm={async () => {
          if (!selectedId || !deleteFolderPath) return;
          const folderFiles = files.filter((f) =>
            f.path.startsWith(deleteFolderPath + "/"),
          );
          // Recursive dir delete handles both empty dirs (no files inside) and
          // non-empty dirs in a single call.
          await dockerfilesApi.deleteDir(selectedId, deleteFolderPath);
          await qc.invalidateQueries({ queryKey: ["dockerfile", selectedId] });
          if (selectedFileId && folderFiles.some((f) => f.id === selectedFileId)) {
            setSelectedFileId(null);
            setDraftContent(null);
          }
        }}
      />

      <ConfirmDialog
        open={importFile !== null}
        onOpenChange={(open) => !open && setImportFile(null)}
        title={t("dockerfiles.import.confirm_title")}
        description={t("dockerfiles.import.confirm_message", {
          filename: importFile?.name ?? "",
        })}
        confirmLabel={t("dockerfiles.import.confirm_button")}
        destructive
        onConfirm={handleImportConfirm}
      />

      <ImportErrorsDialog
        errors={actionErrors}
        onClose={() => setActionErrors([])}
      />

      <UnsavedChangesDialog
        open={pendingNavigation !== null}
        filePath={selectedFile?.path ?? ""}
        onSave={handleSaveAndContinue}
        onDiscard={handleDiscardAndContinue}
        onCancel={handleCancelNavigation}
      />

      {chatOpenFor && (
        <ChatWindow
          dockerfileId={chatOpenFor}
          onClose={() => setChatOpenFor(null)}
          secrets={decryptedSecrets ?? undefined}
          dockerfileJsonContent={dockerfileJsonFile?.content ?? null}
        />
      )}

      {logsContainer && (
        <LogsWindow
          containerId={logsContainer.id}
          containerName={logsContainer.name}
          onClose={() => setLogsContainer(null)}
        />
      )}

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
    </div>
  );
}

interface UnsavedChangesDialogProps {
  open: boolean;
  filePath: string;
  onSave: () => Promise<void> | void;
  onDiscard: () => void;
  onCancel: () => void;
}

function UnsavedChangesDialog({
  open,
  filePath,
  onSave,
  onDiscard,
  onCancel,
}: UnsavedChangesDialogProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("dockerfiles.unsaved.title")}</DialogTitle>
          <DialogDescription>
            {t("dockerfiles.unsaved.message", { path: filePath })}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={saving}
          >
            {t("dockerfiles.unsaved.cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={onDiscard}
            disabled={saving}
          >
            {t("dockerfiles.unsaved.discard")}
          </Button>
          <Button type="button" onClick={handleSave} disabled={saving}>
            {t("dockerfiles.unsaved.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ImportErrorsDialogProps {
  errors: string[];
  onClose: () => void;
}

function ImportErrorsDialog({ errors, onClose }: ImportErrorsDialogProps) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={errors.length > 0}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("dockerfiles.action_errors_title")}</DialogTitle>
          <DialogDescription>
            {t("dockerfiles.action_errors_subtitle")}
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-1 list-disc list-inside text-[13px] text-destructive">
          {errors.map((err, i) => (
            <li key={i}>{err}</li>
          ))}
        </ul>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("dockerfiles.action_errors_close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
