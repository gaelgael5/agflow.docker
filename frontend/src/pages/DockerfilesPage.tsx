import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useDockerfileDetail,
  useDockerfiles,
} from "@/hooks/useDockerfiles";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import { BuildModal } from "@/components/BuildModal";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { dockerfilesApi } from "@/lib/dockerfilesApi";

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

  const detail = useDockerfileDetail(selectedId);
  const currentDockerfile = detail.data?.dockerfile ?? null;
  const files = detail.data?.files ?? [];
  const selectedFile = files.find((f) => f.id === selectedFileId) ?? null;

  async function handleCreate() {
    const id = window.prompt(t("dockerfiles.new_dockerfile_id_prompt"));
    if (!id) return;
    const display_name =
      window.prompt(t("dockerfiles.new_dockerfile_name_prompt")) ?? id;
    const created = await createMutation.mutateAsync({ id, display_name });
    setSelectedId(created.id);
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
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Left: dockerfile list */}
      <aside
        style={{
          minWidth: 240,
          borderRight: "1px solid #ddd",
          padding: "1rem",
          background: "#fafafa",
        }}
      >
        <h2>{t("dockerfiles.page_title")}</h2>
        <button type="button" onClick={handleCreate}>
          {t("dockerfiles.add_button")}
        </button>
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
          <main style={{ flex: 1, padding: "1.5rem", overflowY: "auto" }}>
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
              <div>
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
                  </strong>
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    {draftContent !== null && (
                      <button type="button" onClick={handleSaveFile}>
                        {t("dockerfiles.save_button")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleDeleteFile}
                      style={{ color: "red" }}
                    >
                      {t("dockerfiles.delete_button")}
                    </button>
                  </span>
                </div>
                <MarkdownEditor
                  value={draftContent ?? selectedFile.content}
                  onChange={(v) => setDraftContent(v)}
                  minHeight={420}
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
