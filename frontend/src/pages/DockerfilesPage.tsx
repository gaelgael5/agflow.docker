import { useState } from "react";
import { useTranslation } from "react-i18next";
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
    // 1. Create the dockerfile — this auto-seeds empty Dockerfile + entrypoint.sh
    await createMutation.mutateAsync({
      id: dockerfileId,
      display_name: displayName,
    });
    // 2. Fetch the detail to get the auto-seeded file UUIDs
    const fresh = await dockerfilesApi.get(dockerfileId);
    const dfFile = fresh.files.find((f) => f.path === "Dockerfile");
    const epFile = fresh.files.find((f) => f.path === "entrypoint.sh");
    // 3. Overwrite the 2 standard files with the generated content
    if (dfFile) {
      await dockerfilesApi.updateFile(dockerfileId, dfFile.id, generated.dockerfile);
    }
    if (epFile) {
      await dockerfilesApi.updateFile(
        dockerfileId,
        epFile.id,
        generated.entrypoint_sh,
      );
    }
    // 4. Create run.cmd.md as an additional (non-standard) file
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

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div
      style={{
        display: "flex",
        height: "100%",
        minHeight: "calc(100vh - 56px)",
        overflow: "hidden",
      }}
    >
      {/* Left: dockerfile list */}
      <aside
        style={{
          minWidth: 240,
          borderRight: "1px solid #ddd",
          padding: "1rem",
          background: "#fafafa",
          overflowY: "auto",
        }}
      >
        <h2>{t("dockerfiles.page_title")}</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <button type="button" onClick={handleCreate}>
            {t("dockerfiles.add_button")}
          </button>
          <button type="button" onClick={() => setShowChat(true)}>
            {t("dockerfiles.chat.open_button")}
          </button>
        </div>
        {(dockerfiles ?? []).length === 0 ? (
          <p style={{ color: "#999", fontStyle: "italic" }}>
            {t("dockerfiles.no_dockerfiles")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, marginTop: "1rem" }}>
            {dockerfiles?.map((d) => (
              <li key={d.id} style={{ marginBottom: "0.5rem" }}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedId(d.id);
                    setSelectedFileId(null);
                    setDraftContent(null);
                  }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "8px",
                    background:
                      selectedId === d.id ? "#e0e7ff" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <strong>{d.display_name}</strong>
                  <BuildStatusBadge status={d.display_status} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedId && (
          <button
            type="button"
            onClick={handleDelete}
            style={{ marginTop: "2rem", color: "red" }}
          >
            {t("dockerfiles.delete_button")}
          </button>
        )}
      </aside>

      {selectedId && currentDockerfile ? (
        <>
          {/* Middle: files list */}
          <aside
            style={{
              minWidth: 220,
              borderRight: "1px solid #ddd",
              padding: "1rem",
              overflowY: "auto",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "0.5rem",
              }}
            >
              <strong>Files</strong>
              <button type="button" onClick={handleAddFile}>
                {t("dockerfiles.new_file_button")}
              </button>
            </div>
            {files.length === 0 ? (
              <p style={{ color: "#999", fontStyle: "italic" }}>
                {t("dockerfiles.no_files")}
              </p>
            ) : (
              <ul style={{ listStyle: "none", padding: 0 }}>
                {files.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedFileId(f.id);
                        setDraftContent(null);
                      }}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        padding: "4px 6px",
                        background:
                          selectedFileId === f.id
                            ? "#e0e7ff"
                            : "transparent",
                        border: "none",
                        cursor: "pointer",
                        fontFamily: "monospace",
                        fontSize: "13px",
                      }}
                    >
                      {f.path}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Right: editor */}
          <main
            style={{
              flex: 1,
              padding: "1.5rem",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              minWidth: 0,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1rem",
              }}
            >
              <div>
                <h2 style={{ margin: 0 }}>{currentDockerfile.display_name}</h2>
                <p style={{ fontSize: "12px", color: "#666" }}>
                  {t("dockerfiles.current_hash")}:{" "}
                  <code>{currentDockerfile.current_hash}</code>
                </p>
                <BuildStatusBadge status={currentDockerfile.display_status} />
              </div>
              <button type="button" onClick={handleBuild}>
                {t("dockerfiles.build_button")}
              </button>
            </div>

            {selectedFile ? (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  flex: 1,
                  minHeight: 0,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "0.5rem",
                  }}
                >
                  <strong style={{ fontFamily: "monospace" }}>
                    {selectedFile.path}
                    {(STANDARD_FILES as readonly string[]).includes(
                      selectedFile.path,
                    ) && (
                      <span
                        style={{
                          marginLeft: "0.5rem",
                          fontSize: "11px",
                          color: "#666",
                          fontFamily: "system-ui",
                        }}
                      >
                        ({t("dockerfiles.standard_file")})
                      </span>
                    )}
                  </strong>
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    {draftContent !== null && (
                      <button type="button" onClick={handleSaveFile}>
                        {t("dockerfiles.save_button")}
                      </button>
                    )}
                    {!(STANDARD_FILES as readonly string[]).includes(
                      selectedFile.path,
                    ) && (
                      <button
                        type="button"
                        onClick={handleDeleteFile}
                        style={{ color: "red" }}
                      >
                        {t("dockerfiles.delete_button")}
                      </button>
                    )}
                  </span>
                </div>
                <MarkdownEditor
                  value={draftContent ?? selectedFile.content}
                  onChange={(v) => setDraftContent(v)}
                  fill
                />
              </div>
            ) : (
              <p style={{ color: "#888" }}>
                {t("dockerfiles.no_files")} —{" "}
                {t("dockerfiles.new_file_button")}
              </p>
            )}
          </main>
        </>
      ) : (
        <main style={{ flex: 1, padding: "2rem", color: "#888" }}>
          <p>{t("dockerfiles.select_dockerfile")}</p>
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
