import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Lock, Plus, Save, Trash2, Upload } from "lucide-react";
import { useRoles } from "@/hooks/useRoles";
import {
  useRoleDetail,
  useRoleDocumentMutations,
} from "@/hooks/useRoleDocuments";
import { RoleSidebar, isDocLocked, docDisplayName } from "@/components/RoleSidebar";
import { RoleGeneralTab } from "@/components/RoleGeneralTab";
import { RolePromptTab } from "@/components/RolePromptTab";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { ConfirmDialog } from "@/components/ConfirmDialog";
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
import { rolesApi, type RoleSummary, type Section } from "@/lib/rolesApi";

type Tab = "general" | "prompt" | "document";

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
  const [showDeleteRoleConfirm, setShowDeleteRoleConfirm] = useState(false);
  const [deleteSectionTarget, setDeleteSectionTarget] = useState<string | null>(null);
  const [draftDocContent, setDraftDocContent] = useState<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

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
    await deleteMutation.mutateAsync(selectedRoleId);
    setSelectedRoleId(null);
    setDraftRole(null);
  }

  async function handleExportRole() {
    if (!selectedRoleId) return;
    const blob = await rolesApi.exportZip(selectedRoleId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedRoleId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleImportRole(file: File) {
    if (!selectedRoleId) return;
    await rolesApi.importZip(selectedRoleId, file);
    detail.refetch();
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
    setTab("document");
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

  async function handleDeleteSection() {
    if (!selectedRoleId || !deleteSectionTarget) return;
    await docMutations.deleteSection.mutateAsync(deleteSectionTarget);
  }

  const flushDocDraft = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
  }, []);

  function handleDocumentChange(content: string) {
    if (!selectedDoc || !selectedRoleId) return;
    setDraftDocContent(content);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      docMutations.updateDoc.mutate({
        docId: selectedDoc.id,
        payload: { content_md: content },
      });
      setDraftDocContent(null);
      saveTimerRef.current = null;
    }, 800);
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
      <div className="flex items-center gap-3 px-4 py-2.5 border-b bg-muted/30 shrink-0">
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

        <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={() => setShowCreateRoleDialog(true)}
            title={t("roles.add_button")}
          >
            <Plus className="w-3.5 h-3.5" />
          </Button>
        </div>

        {selectedRoleId && currentRole && (
          <>
            <span className="text-[12px] text-muted-foreground font-mono">
              {currentRole.id}
            </span>
            <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5 ml-auto">
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={handleExportRole}
                title={t("common.export")}
              >
                <Download className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => importInputRef.current?.click()}
                title={t("common.import")}
              >
                <Upload className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-destructive"
                onClick={() => setShowDeleteRoleConfirm(true)}
                title={t("roles.delete_button")}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
            <input
              ref={importInputRef}
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleImportRole(f);
                e.target.value = "";
              }}
            />
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
              onSelect={(id) => { flushDocDraft(); setDraftDocContent(null); setSelectedDocId(id); setTab("document"); }}
              onAdd={handleAddDocument}
              onAddSection={() => {
                setSectionError(null);
                setShowAddSectionDialog(true);
              }}
              onDeleteSection={(name) => setDeleteSectionTarget(name)}
              onToggleLock={(doc) => {
                const newName = isDocLocked(doc)
                  ? doc.name.slice(0, -1)
                  : doc.name + "_";
                docMutations.updateDoc.mutate({
                  docId: doc.id,
                  payload: { name: newName },
                });
              }}
            />

            {/* Right: main content */}
            <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
              <div className="px-6 py-4 border-b shrink-0">
                <h2 className="text-[18px] font-semibold text-foreground truncate">
                  {currentRole.display_name}
                </h2>
                <p className="text-[12px] text-muted-foreground font-mono mt-0.5">
                  {currentRole.id}
                </p>
              </div>

              <div className={`flex-1 min-h-0 px-6 py-5 flex flex-col ${tab === "document" ? "" : "overflow-y-auto"}`}>
                <Tabs
                  value={tab}
                  onValueChange={(v) => {
                    setTab(v as Tab);
                    if (v !== "document") {
                      flushDocDraft();
                      setDraftDocContent(null);
                      setSelectedDocId(null);
                    }
                  }}
                  className={tab === "document" ? "flex-1 flex flex-col min-h-0" : ""}
                >
                  <TabsList>
                    <TabsTrigger value="general">
                      {t("roles.tab_general")}
                    </TabsTrigger>
                    <TabsTrigger value="prompt">
                      {t("roles.tab_prompt")}
                    </TabsTrigger>
                    {selectedDoc && (
                      <TabsTrigger value="document">
                        {docDisplayName(selectedDoc)}
                      </TabsTrigger>
                    )}
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

                  {selectedDoc && (
                    <TabsContent value="document" className="flex-1 flex flex-col min-h-0">
                      <div className="flex items-center gap-2 mb-3 shrink-0">
                        <h3 className="text-[15px] font-semibold">
                          {docDisplayName(selectedDoc)}
                        </h3>
                        {isDocLocked(selectedDoc) && (
                          <Lock className="w-3.5 h-3.5 text-amber-500" />
                        )}
                      </div>
                      <MarkdownEditor
                        value={draftDocContent ?? selectedDoc.content_md}
                        onChange={handleDocumentChange}
                        readOnly={isDocLocked(selectedDoc)}
                        fill
                      />
                    </TabsContent>
                  )}
                </Tabs>
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

      <ConfirmDialog
        open={showDeleteRoleConfirm}
        onOpenChange={setShowDeleteRoleConfirm}
        title={t("roles.confirm_delete_title")}
        description={t("roles.confirm_delete_message", { name: currentRole?.display_name ?? "" })}
        destructive
        onConfirm={handleDeleteRole}
      />

      <ConfirmDialog
        open={deleteSectionTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteSectionTarget(null); }}
        title={t("roles.confirm_delete_section_title")}
        description={t("roles.confirm_delete_section_message", { name: deleteSectionTarget ?? "" })}
        destructive
        onConfirm={handleDeleteSection}
      />
    </div>
  );
}
