import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useRoles } from "@/hooks/useRoles";
import {
  useRoleDetail,
  useRoleDocumentMutations,
} from "@/hooks/useRoleDocuments";
import { RoleSidebar } from "@/components/RoleSidebar";
import { RoleGeneralTab } from "@/components/RoleGeneralTab";
import { RolePromptTab } from "@/components/RolePromptTab";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import type { RoleSummary, Section } from "@/lib/rolesApi";
import { slugify } from "@/lib/slugify";

type Tab = "general" | "prompt" | "chat";

export function RolesPage() {
  const { t } = useTranslation();
  const {
    roles,
    isLoading,
    createMutation,
    updateMutation,
    deleteMutation,
    generateMutation,
  } = useRoles();

  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("general");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [draftRole, setDraftRole] = useState<RoleSummary | null>(null);

  const detail = useRoleDetail(selectedRoleId);
  const docMutations = useRoleDocumentMutations(selectedRoleId ?? "");

  const currentRole = draftRole ?? detail.data?.role ?? null;
  const sections = detail.data?.sections ?? [];
  const allDocuments = sections.flatMap((s) => s.documents);
  const selectedDoc = allDocuments.find((d) => d.id === selectedDocId) ?? null;

  async function handleCreateRole() {
    const display_name = window.prompt(t("roles.general.display_name"));
    if (!display_name) return;
    const id = window.prompt(t("roles.general.id"), slugify(display_name));
    if (!id) return;
    const created = await createMutation.mutateAsync({ id, display_name });
    setSelectedRoleId(created.id);
    setTab("general");
  }

  async function handleDeleteRole() {
    if (!selectedRoleId) return;
    if (!window.confirm(`${t("roles.delete_button")} "${selectedRoleId}"?`))
      return;
    await deleteMutation.mutateAsync(selectedRoleId);
    setSelectedRoleId(null);
    setDraftRole(null);
  }

  async function handleSaveRole() {
    if (!draftRole || !selectedRoleId) return;
    await updateMutation.mutateAsync({
      id: selectedRoleId,
      payload: {
        display_name: draftRole.display_name,
        description: draftRole.description,
        service_types: draftRole.service_types,
        identity_md: draftRole.identity_md,
      },
    });
    setDraftRole(null);
  }

  async function handleGenerate() {
    if (!selectedRoleId) return;
    setGenerateError(null);
    try {
      await generateMutation.mutateAsync(selectedRoleId);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      const detailText =
        (err as { response?: { data?: { detail?: string } } }).response?.data
          ?.detail ?? t("roles.errors.generic");
      if (status === 412) {
        setGenerateError(t("roles.errors.missing_anthropic_key"));
      } else {
        setGenerateError(detailText);
      }
    }
  }

  async function handleAddDocument(section: Section) {
    if (!selectedRoleId) return;
    const name = window.prompt(t("roles.sidebar.new_document_name"));
    if (!name) return;
    const doc = await docMutations.createDoc.mutateAsync({
      section,
      name,
      content_md: "",
      protected: false,
    });
    setSelectedDocId(doc.id);
  }

  async function handleAddSection() {
    if (!selectedRoleId) return;
    const display_name = window.prompt(
      t("roles.sidebar.new_section_display_name"),
    );
    if (!display_name) return;
    const name = window.prompt(
      t("roles.sidebar.new_section_slug"),
      slugify(display_name),
    );
    if (!name) return;
    try {
      await docMutations.createSection.mutateAsync({ name, display_name });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      window.alert(detail ?? t("roles.errors.generic"));
    }
  }

  async function handleDeleteSection(name: string) {
    if (!selectedRoleId) return;
    if (!window.confirm(t("roles.sidebar.confirm_delete_section", { name })))
      return;
    try {
      await docMutations.deleteSection.mutateAsync(name);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      window.alert(detail ?? t("roles.errors.generic"));
    }
  }

  async function handleDocumentChange(content: string) {
    if (!selectedDoc || !selectedRoleId) return;
    await docMutations.updateDoc.mutateAsync({
      docId: selectedDoc.id,
      payload: { content_md: content },
    });
  }

  function handleRoleFieldChange(updates: Partial<RoleSummary>) {
    if (!currentRole) return;
    setDraftRole({ ...currentRole, ...updates });
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <aside
        style={{
          minWidth: 240,
          borderRight: "1px solid #ddd",
          padding: "1rem",
          background: "#fafafa",
        }}
      >
        <h2>{t("roles.page_title")}</h2>
        <button type="button" onClick={handleCreateRole}>
          {t("roles.add_button")}
        </button>
        {(roles ?? []).length === 0 ? (
          <p style={{ color: "#999", fontStyle: "italic" }}>
            {t("roles.no_roles")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, marginTop: "1rem" }}>
            {roles?.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedRoleId(r.id);
                    setSelectedDocId(null);
                    setDraftRole(null);
                  }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "6px",
                    background:
                      selectedRoleId === r.id ? "#e0e7ff" : "transparent",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  {r.display_name}
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedRoleId && (
          <button
            type="button"
            onClick={handleDeleteRole}
            style={{ marginTop: "2rem", color: "red" }}
          >
            {t("roles.delete_button")}
          </button>
        )}
      </aside>

      {selectedRoleId && detail.data && currentRole ? (
        <>
          <RoleSidebar
            sections={sections}
            documents={allDocuments}
            selectedDocId={selectedDocId}
            onSelect={setSelectedDocId}
            onAdd={handleAddDocument}
            onAddSection={handleAddSection}
            onDeleteSection={handleDeleteSection}
          />
          <main style={{ flex: 1, padding: "1.5rem", overflowY: "auto" }}>
            <nav style={{ marginBottom: "1rem", display: "flex", gap: "1rem" }}>
              {(["general", "prompt", "chat"] as Tab[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => {
                    setTab(name);
                    setSelectedDocId(null);
                  }}
                  style={{
                    fontWeight: tab === name ? 700 : 400,
                    border: "none",
                    background: "none",
                    cursor: "pointer",
                  }}
                >
                  {t(`roles.tab_${name}`)}
                </button>
              ))}
            </nav>

            {selectedDoc ? (
              <div>
                <h3>{selectedDoc.name}</h3>
                <MarkdownEditor
                  value={selectedDoc.content_md}
                  onChange={handleDocumentChange}
                  readOnly={selectedDoc.protected}
                />
              </div>
            ) : (
              <>
                {tab === "general" && (
                  <>
                    <RoleGeneralTab
                      role={currentRole}
                      onChange={handleRoleFieldChange}
                    />
                    {draftRole && (
                      <button
                        type="button"
                        onClick={handleSaveRole}
                        style={{ marginTop: "1rem" }}
                      >
                        {t("roles.save")}
                      </button>
                    )}
                  </>
                )}
                {tab === "prompt" && (
                  <RolePromptTab
                    role={currentRole}
                    onRegenerate={handleGenerate}
                    regenerating={generateMutation.isPending}
                    error={generateError}
                  />
                )}
                {tab === "chat" && (
                  <p style={{ color: "#888", fontStyle: "italic" }}>
                    {t("roles.chat_placeholder")}
                  </p>
                )}
              </>
            )}
          </main>
        </>
      ) : (
        <main style={{ flex: 1, padding: "2rem", color: "#888" }}>
          <p>{t("roles.select_role")}</p>
        </main>
      )}
    </div>
  );
}
