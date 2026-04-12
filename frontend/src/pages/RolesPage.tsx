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
import { PromptDialog } from "@/components/PromptDialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import type { RoleSummary, Section } from "@/lib/rolesApi";

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
  const [showCreateRoleDialog, setShowCreateRoleDialog] = useState(false);
  const [addDocSection, setAddDocSection] = useState<Section | null>(null);
  const [showAddSectionDialog, setShowAddSectionDialog] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);

  const detail = useRoleDetail(selectedRoleId);
  const docMutations = useRoleDocumentMutations(selectedRoleId ?? "");

  const currentRole = draftRole ?? detail.data?.role ?? null;
  const sections = detail.data?.sections ?? [];
  const allDocuments = sections.flatMap((s) => s.documents);
  const selectedDoc = allDocuments.find((d) => d.id === selectedDocId) ?? null;

  async function handleCreateRole(values: Record<string, string>) {
    const created = await createMutation.mutateAsync({
      id: values.id ?? "",
      display_name: values.display_name ?? "",
    });
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

  function handleAddDocument(section: Section) {
    if (!selectedRoleId) return;
    setAddDocSection(section);
  }

  async function handleAddDocumentSubmit(values: Record<string, string>) {
    if (!selectedRoleId || !addDocSection) return;
    const doc = await docMutations.createDoc.mutateAsync({
      section: addDocSection,
      name: values.name ?? "",
      content_md: "",
      protected: false,
    });
    setSelectedDocId(doc.id);
  }

  async function handleAddSectionSubmit(values: Record<string, string>) {
    if (!selectedRoleId) return;
    setSectionError(null);
    try {
      await docMutations.createSection.mutateAsync({
        name: values.name ?? "",
        display_name: values.display_name ?? "",
      });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setSectionError(detail ?? t("roles.errors.generic"));
      throw e;
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
    <div className="flex flex-col h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Header row: dropdown + action buttons */}
      <div className="flex items-center gap-2 px-4 py-3 border-b bg-background shrink-0 flex-wrap">
        <Select
          value={selectedRoleId ?? ""}
          onValueChange={(value) => {
            setSelectedRoleId(value || null);
            setSelectedDocId(null);
            setDraftRole(null);
          }}
        >
          <SelectTrigger className="w-56">
            <SelectValue placeholder={t("roles.select_role")} />
          </SelectTrigger>
          <SelectContent>
            {(roles ?? []).map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {r.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          size="sm"
          variant="outline"
          onClick={() => setShowCreateRoleDialog(true)}
        >
          <Plus className="w-3.5 h-3.5" />
          {t("roles.add_button")}
        </Button>

        {selectedRoleId && currentRole && (
          <>
            <div className="w-px h-5 bg-border mx-1 shrink-0" />
            <span className="text-[12px] text-muted-foreground font-mono">
              {currentRole.id}
            </span>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDeleteRole}
              className="text-destructive ml-auto"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {t("roles.delete_button")}
            </Button>
          </>
        )}
      </div>

      {/* Body: RoleSidebar + main content */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {selectedRoleId && detail.data && currentRole ? (
          <>
            {/* Left: documents sidebar */}
            <RoleSidebar
              sections={sections}
              documents={allDocuments}
              selectedDocId={selectedDocId}
              onSelect={setSelectedDocId}
              onAdd={handleAddDocument}
              onAddSection={() => {
                setSectionError(null);
                setShowAddSectionDialog(true);
              }}
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

      <PromptDialog
        open={showCreateRoleDialog}
        onOpenChange={setShowCreateRoleDialog}
        title={t("roles.new_role_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleCreateRole}
        fields={[
          { name: "display_name", label: t("roles.general.display_name") },
          {
            name: "id",
            label: t("roles.general.id"),
            autoSlugFrom: "display_name",
            monospace: true,
          },
        ]}
      />

      <PromptDialog
        open={addDocSection !== null}
        onOpenChange={(open) => !open && setAddDocSection(null)}
        title={t("roles.sidebar.new_document_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleAddDocumentSubmit}
        fields={[
          { name: "name", label: t("roles.sidebar.new_document_name") },
        ]}
      />

      <PromptDialog
        open={showAddSectionDialog}
        onOpenChange={setShowAddSectionDialog}
        title={t("roles.sidebar.new_section_dialog_title")}
        description={sectionError ?? undefined}
        submitLabel={t("common.create")}
        onSubmit={handleAddSectionSubmit}
        fields={[
          {
            name: "display_name",
            label: t("roles.sidebar.new_section_display_name"),
          },
          {
            name: "name",
            label: t("roles.sidebar.new_section_slug"),
            autoSlugFrom: "display_name",
            monospace: true,
          },
        ]}
      />
    </div>
  );
}
