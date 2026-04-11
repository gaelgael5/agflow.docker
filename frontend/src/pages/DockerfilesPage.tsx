import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bot, FileCode2, Hammer, Plus, Save, Trash2 } from "lucide-react";
import {
  useDockerfileDetail,
  useDockerfiles,
} from "@/hooks/useDockerfiles";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import { BuildModal } from "@/components/BuildModal";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { DockerChatModal } from "@/components/DockerChatModal";
import { dockerfilesApi } from "@/lib/dockerfilesApi";
import { slugify } from "@/lib/slugify";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const STANDARD_FILES = ["Dockerfile", "entrypoint.sh"] as const;

export function DockerfilesPage() {
  const { t } = useTranslation();
  const {
    dockerfiles,
    isLoading,
    createMutation,
    deleteMutation,
    createFileMutation,
    updateFileMutation,
    deleteFileMutation,
  } = useDockerfiles();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [draftContent, setDraftContent] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);

  const detail = useDockerfileDetail(selectedId);
  const currentDockerfile = detail.data?.dockerfile ?? null;
  const files = detail.data?.files ?? [];
  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;

  async function handleCreate() {
    const display_name = window.prompt(
      t("dockerfiles.new_dockerfile_name_prompt"),
    );
    if (!display_name) return;
    const id = window.prompt(
      t("dockerfiles.new_dockerfile_id_prompt"),
      slugify(display_name),
    );
    if (!id) return;
    const created = await createMutation.mutateAsync({ id, display_name });
    setSelectedId(created.id);
  }

  async function handleAcceptGenerated(
    dockerfileId: string,
    displayName: string,
    generated: {
      dockerfile: string;
      entrypoint_sh: string;
      run_cmd_md: string;
    },
  ) {
    await createMutation.mutateAsync({
      id: dockerfileId,
      display_name: displayName,
    });
    const fresh = await dockerfilesApi.get(dockerfileId);
    const dfFile = fresh.files.find((f) => f.path === "Dockerfile");
    const epFile = fresh.files.find((f) => f.path === "entrypoint.sh");
    if (dfFile) {
      await dockerfilesApi.updateFile(
        dockerfileId,
        dfFile.id,
        generated.dockerfile,
      );
    }
    if (epFile) {
      await dockerfilesApi.updateFile(
        dockerfileId,
        epFile.id,
        generated.entrypoint_sh,
      );
    }
    await dockerfilesApi.createFile(dockerfileId, {
      path: "run.cmd.md",
      content: generated.run_cmd_md,
    });
    setSelectedId(dockerfileId);
  }

  async function handleDelete() {
    if (!selectedId) return;
    if (!window.confirm(t("dockerfiles.confirm_delete", { name: selectedId })))
      return;
    await deleteMutation.mutateAsync(selectedId);
    setSelectedId(null);
    setSelectedFileId(null);
    setDraftContent(null);
  }

  async function handleAddFile() {
    if (!selectedId) return;
    const path = window.prompt(t("dockerfiles.new_file_prompt"));
    if (!path) return;
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

  async function handleDeleteFile() {
    if (!selectedId || !selectedFile) return;
    await deleteFileMutation.mutateAsync({
      dockerfileId: selectedId,
      fileId: selectedFile.id,
    });
    setSelectedFileId(null);
    setDraftContent(null);
  }

  async function handleBuild() {
    if (!selectedId) return;
    const res = await dockerfilesApi.build(selectedId);
    setBuildId(res.id);
  }

  if (isLoading)
    return <p className="p-6 text-muted-foreground">{t("secrets.loading")}</p>;

  const isStandard =
    selectedFile !== null &&
    (STANDARD_FILES as readonly string[]).includes(selectedFile.path);

  return (
    <div className="flex h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Left column: dockerfile list */}
      <aside className="w-64 shrink-0 border-r bg-muted/30 flex flex-col overflow-hidden">
        <div className="p-4 border-b">
          <h2 className="text-[13px] font-semibold text-foreground uppercase tracking-wider mb-2">
            {t("dockerfiles.page_title")}
          </h2>
          <div className="flex flex-col gap-1.5">
            <Button size="sm" onClick={handleCreate} className="w-full">
              <Plus className="w-3.5 h-3.5" />
              {t("dockerfiles.add_button")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowChat(true)}
              className="w-full"
            >
              <Bot className="w-3.5 h-3.5" />
              {t("dockerfiles.chat.open_button_short")}
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {(dockerfiles ?? []).length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic px-2 py-2">
              {t("dockerfiles.no_dockerfiles")}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {dockerfiles?.map((d) => {
                const active = selectedId === d.id;
                return (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedId(d.id);
                        setSelectedFileId(null);
                        setDraftContent(null);
                      }}
                      className={cn(
                        "w-full text-left px-2.5 py-2 rounded-md transition-colors",
                        active
                          ? "bg-primary/10 text-primary"
                          : "hover:bg-secondary text-foreground",
                      )}
                    >
                      <div className="font-medium text-[13px] truncate">
                        {d.display_name}
                      </div>
                      <div className="mt-1">
                        <BuildStatusBadge status={d.display_status} />
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {selectedId && (
          <div className="p-3 border-t">
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDelete}
              className="w-full text-destructive"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {t("dockerfiles.delete_button")}
            </Button>
          </div>
        )}
      </aside>

      {selectedId && currentDockerfile ? (
        <>
          {/* Middle column: files list */}
          <aside className="w-56 shrink-0 border-r flex flex-col overflow-hidden">
            <div className="p-3 border-b flex items-center justify-between">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                {t("dockerfiles.files_title")}
              </span>
              <Button
                size="icon"
                variant="ghost"
                onClick={handleAddFile}
                aria-label={t("dockerfiles.new_file_button")}
              >
                <Plus className="w-3.5 h-3.5" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {files.length === 0 ? (
                <p className="text-muted-foreground text-[12px] italic px-2 py-2">
                  {t("dockerfiles.no_files")}
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {files.map((f) => {
                    const active = selectedFileId === f.id;
                    return (
                      <li key={f.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedFileId(f.id);
                            setDraftContent(null);
                          }}
                          className={cn(
                            "w-full text-left px-2.5 py-1.5 rounded-md font-mono text-[12px] flex items-center gap-2 transition-colors",
                            active
                              ? "bg-primary/10 text-primary"
                              : "hover:bg-secondary text-foreground",
                          )}
                        >
                          <FileCode2 className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{f.path}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </aside>

          {/* Right column: editor */}
          <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
            <div className="flex items-start justify-between gap-3 px-6 pt-5 pb-4 border-b">
              <div className="min-w-0">
                <h2 className="text-[18px] font-semibold text-foreground truncate">
                  {currentDockerfile.display_name}
                </h2>
                <div className="flex items-center gap-2 mt-1">
                  <BuildStatusBadge status={currentDockerfile.display_status} />
                  <span className="text-[11px] text-muted-foreground">
                    {t("dockerfiles.current_hash")}:{" "}
                    <code className="font-mono">
                      {currentDockerfile.current_hash}
                    </code>
                  </span>
                </div>
              </div>
              <Button onClick={handleBuild}>
                <Hammer className="w-4 h-4" />
                {t("dockerfiles.build_button")}
              </Button>
            </div>

            {selectedFile ? (
              <div className="flex-1 flex flex-col min-h-0 px-6 py-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <code className="font-mono text-[13px] font-semibold">
                      {selectedFile.path}
                    </code>
                    {isStandard && (
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
                    {!isStandard && (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={handleDeleteFile}
                        aria-label={t("dockerfiles.delete_button")}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    )}
                  </div>
                </div>
                <MarkdownEditor
                  value={draftContent ?? selectedFile.content}
                  onChange={(v) => setDraftContent(v)}
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
          onClose={() => setBuildId(null)}
        />
      )}
    </div>
  );
}
