import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Save, Trash2 } from "lucide-react";
import { useRoles } from "@/hooks/useRoles";
import {
  useRoleDetail,
  useRoleDocumentMutations,
} from "@/hooks/useRoleDocuments";
import { RoleSidebar } from "@/components/RoleSidebar";
import { RoleGeneralTab } from "@/components/RoleGeneralTab";
import { RolePromptTab } from "@/components/RolePromptTab";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
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

  if (isLoading)
    return <p className="p-6 text-muted-foreground">{t("secrets.loading")}</p>;

  return (
    <div className="flex h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Left: roles list */}
      <aside className="w-64 shrink-0 border-r bg-muted/30 flex flex-col overflow-hidden">
        <div className="p-4 border-b">
          <h2 className="text-[13px] font-semibold text-foreground uppercase tracking-wider mb-2">
            {t("roles.page_title")}
          </h2>
          <Button size="sm" onClick={handleCreateRole} className="w-full">
            <Plus className="w-3.5 h-3.5" />
            {t("roles.add_button")}
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {(roles ?? []).length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic px-2 py-2">
              {t("roles.no_roles")}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {roles?.map((r) => {
                const active = selectedRoleId === r.id;
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedRoleId(r.id);
                        setSelectedDocId(null);
                        setDraftRole(null);
                      }}
                      className={cn(
                        "w-full text-left px-2.5 py-2 rounded-md text-[13px] font-medium transition-colors",
                        active
                          ? "bg-primary/10 text-primary"
                          : "hover:bg-secondary text-foreground",
                      )}
                    >
                      {r.display_name}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {selectedRoleId && (
          <div className="p-3 border-t">
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDeleteRole}
              className="w-full text-destructive"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {t("roles.delete_button")}
            </Button>
          </div>
        )}
      </aside>

      {selectedRoleId && detail.data && currentRole ? (
        <>
          {/* Middle: documents sidebar */}
          <RoleSidebar
            sections={sections}
            documents={allDocuments}
            selectedDocId={selectedDocId}
            onSelect={setSelectedDocId}
            onAdd={handleAddDocument}
            onAddSection={handleAddSection}
            onDeleteSection={handleDeleteSection}
          />

          {/* Right: main content */}
          <main className="flex-1 min-w-0 overflow-y-auto">
            <div className="px-6 py-5 border-b">
              <h2 className="text-[18px] font-semibold text-foreground truncate">
                {currentRole.display_name}
              </h2>
              <p className="text-[12px] text-muted-foreground font-mono mt-0.5">
                {currentRole.id}
              </p>
            </div>

            <div className="px-6 py-5">
              {selectedDoc ? (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="text-[15px] font-semibold">
                      {selectedDoc.name}
                    </h3>
                    {selectedDoc.protected && (
                      <span className="text-[11px] text-muted-foreground">
                        🔒
                      </span>
                    )}
                  </div>
                  <MarkdownEditor
                    value={selectedDoc.content_md}
                    onChange={handleDocumentChange}
                    readOnly={selectedDoc.protected}
                    minHeight={400}
                  />
                </div>
              ) : (
                <Tabs
                  value={tab}
                  onValueChange={(v) => {
                    setTab(v as Tab);
                    setSelectedDocId(null);
                  }}
                >
                  <TabsList>
                    <TabsTrigger value="general">
                      {t("roles.tab_general")}
                    </TabsTrigger>
                    <TabsTrigger value="prompt">
                      {t("roles.tab_prompt")}
                    </TabsTrigger>
                    <TabsTrigger value="chat">
                      {t("roles.tab_chat")}
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="general">
                    <RoleGeneralTab
                      role={currentRole}
                      onChange={handleRoleFieldChange}
                    />
                    {draftRole && (
                      <div className="mt-4">
                        <Button onClick={handleSaveRole}>
                          <Save className="w-4 h-4" />
                          {t("roles.save")}
                        </Button>
                      </div>
                    )}
                  </TabsContent>

                  <TabsContent value="prompt">
                    <RolePromptTab
                      role={currentRole}
                      onRegenerate={handleGenerate}
                      regenerating={generateMutation.isPending}
                      error={generateError}
                    />
                  </TabsContent>

                  <TabsContent value="chat">
                    <p className="text-muted-foreground italic text-[13px]">
                      {t("roles.chat_placeholder")}
                    </p>
                  </TabsContent>
                </Tabs>
              )}
            </div>
          </main>
        </>
      ) : (
        <main className="flex-1 flex items-center justify-center text-muted-foreground text-[13px] italic">
          {t("roles.select_role")}
        </main>
      )}
    </div>
  );
}
