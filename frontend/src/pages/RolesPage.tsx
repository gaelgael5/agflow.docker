import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Plus, Save, Search, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useRoles } from "@/hooks/useRoles";
import {
  useRoleDetail,
  useRoleDocumentMutations,
} from "@/hooks/useRoleDocuments";
import {
  RoleSidebar,
  isDocLocked,
  docDisplayName,
} from "@/components/RoleSidebar";
import { RoleGeneralTab } from "@/components/RoleGeneralTab";
import { RolePromptTab } from "@/components/RolePromptTab";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PromptDialog } from "@/components/PromptDialog";
import {
  DropConflictDialog,
  type ConflictResolution,
} from "@/components/DropConflictDialog";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { rolesApi, type RoleSummary, type Section } from "@/lib/rolesApi";
import {
  isMarkdownFile,
  sanitizeDocName,
  stripSectionPrefix,
  findFreeName,
  MAX_FILE_SIZE_BYTES,
} from "@/lib/dropFiles";

type Tab = "general" | "prompt" | "document";

type PendingConflict = {
  file: File;
  content: string;
  name: string;
  existingDocId: string;
  suggestedRename: string;
};

export function RolesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
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
  const [deleteSectionTarget, setDeleteSectionTarget] = useState<string | null>(
    null,
  );
  const [draftDocContent, setDraftDocContent] = useState<string | null>(null);
  const [editingDocName, setEditingDocName] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState("");
  const importInputRef = useRef<HTMLInputElement>(null);
  const [conflicts, setConflicts] = useState<PendingConflict[]>([]);
  const pendingSummaryRef = useRef<{
    section: Section;
    created: number;
    replaced: number;
    failed: number;
  } | null>(null);

  const detail = useRoleDetail(selectedRoleId);
  const docMutations = useRoleDocumentMutations(selectedRoleId ?? "");

  const currentRole = draftRole ?? detail.data?.role ?? null;
  const hasDirtyDoc = draftDocContent !== null;
  const hasDirtyRole = draftRole !== null;
  const hasDirty = hasDirtyDoc || hasDirtyRole;

  // Ctrl+S
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (hasDirtyDoc) handleSaveDocument();
        else if (hasDirtyRole) handleSaveRole();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  // beforeunload
  useEffect(() => {
    if (!hasDirty) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasDirty]);
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
      const status = (err as { response?: { status?: number } }).response
        ?.status;
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

  function handleDocumentChange(content: string) {
    if (!selectedDoc || !selectedRoleId) return;
    setDraftDocContent(content);
  }

  async function handleSaveDocument() {
    if (!selectedDoc || !selectedRoleId || draftDocContent === null) return;
    docMutations.updateDoc.mutate({
      docId: selectedDoc.id,
      payload: { content_md: draftDocContent },
    });
    setDraftDocContent(null);
  }

  function handleRoleFieldChange(updates: Partial<RoleSummary>) {
    if (!currentRole) return;
    setDraftRole({ ...currentRole, ...updates });
  }

  function emitFinalToast(
    section: Section,
    created: number,
    replaced: number,
    failed: number,
  ) {
    if (created === 0 && replaced === 0 && failed === 0) return;
    const sectionDisplay =
      sections.find((s) => s.name === section)?.display_name ?? section;
    if (failed === 0 && replaced === 0) {
      toast.success(
        t("roles.drop.toast_success", {
          count: created,
          section: sectionDisplay,
        }),
      );
    } else if (failed === 0 && created === 0) {
      toast.success(
        t("roles.drop.toast_replaced", {
          count: replaced,
          section: sectionDisplay,
        }),
      );
    } else if (created === 0 && replaced === 0) {
      toast.error(t("roles.drop.toast_none"));
    } else {
      toast(t("roles.drop.toast_mixed", { created, replaced, failed }));
    }
  }

  async function handleDropFiles(section: Section, files: File[]) {
    if (!selectedRoleId || !detail.data) return;

    const sectionDocs = allDocuments.filter((d) => d.section === section);
    const existingNames = sectionDocs.map((d) => d.name);
    const existingByName: Record<string, string> = Object.fromEntries(
      sectionDocs.map((d) => [d.name, d.id]),
    );

    const pendingCreates: Array<{ name: string; content: string; file: File }> =
      [];
    const pendingConflicts: PendingConflict[] = [];
    const accumulatedNames = [...existingNames];

    for (const file of files) {
      if (!isMarkdownFile(file)) {
        toast.error(t("roles.drop.error_extension", { name: file.name }));
        continue;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        toast.error(t("roles.drop.error_size", { name: file.name }));
        continue;
      }
      const rawName = sanitizeDocName(file.name);
      if (!rawName) {
        toast.error(t("roles.drop.error_name", { name: file.name }));
        continue;
      }
      let content: string;
      try {
        content = await file.text();
        if (content.includes("\uFFFD")) throw new Error("encoding");
      } catch {
        toast.error(t("roles.drop.error_encoding", { name: file.name }));
        continue;
      }

      const name = stripSectionPrefix(rawName, section);

      if (name in existingByName) {
        pendingConflicts.push({
          file,
          content,
          name,
          existingDocId: existingByName[name]!,
          suggestedRename: findFreeName(name, accumulatedNames),
        });
      } else {
        pendingCreates.push({ name, content, file });
        accumulatedNames.push(name);
      }
    }

    let created = 0;
    let failed = 0;
    for (const item of pendingCreates) {
      try {
        await rolesApi.createDocument(selectedRoleId, {
          section,
          name: item.name,
          content_md: item.content,
        });
        created += 1;
      } catch {
        failed += 1;
        toast.error(t("roles.drop.error_network", { name: item.file.name }));
      }
    }

    if (pendingConflicts.length > 0) {
      setConflicts(pendingConflicts);
      pendingSummaryRef.current = { section, created, replaced: 0, failed };
    } else {
      emitFinalToast(section, created, 0, failed);
      if (created > 0) {
        queryClient.invalidateQueries({ queryKey: ["role", selectedRoleId] });
      }
    }
  }

  async function onResolveConflict(resolution: ConflictResolution) {
    const [head, ...rest] = conflicts;
    if (!head || !selectedRoleId) return;
    const summary = pendingSummaryRef.current;
    if (!summary) return;

    const processConflict = async (
      c: PendingConflict,
      action: ConflictResolution["action"],
    ) => {
      if (action === "replace") {
        try {
          await rolesApi.updateDocument(selectedRoleId, c.existingDocId, {
            content_md: c.content,
          });
          summary.replaced += 1;
        } catch {
          summary.failed += 1;
          toast.error(t("roles.drop.error_network", { name: c.file.name }));
        }
      } else if (action === "rename") {
        try {
          await rolesApi.createDocument(selectedRoleId, {
            section: summary.section,
            name: c.suggestedRename,
            content_md: c.content,
          });
          summary.created += 1;
        } catch {
          summary.failed += 1;
          toast.error(t("roles.drop.error_network", { name: c.file.name }));
        }
      } else {
        summary.failed += 1;
      }
    };

    await processConflict(head, resolution.action);

    let remaining = rest;
    if (resolution.applyToAll && rest.length > 0) {
      for (const c of rest) {
        await processConflict(c, resolution.action);
      }
      remaining = [];
    }

    setConflicts(remaining);
    if (remaining.length === 0) {
      emitFinalToast(
        summary.section,
        summary.created,
        summary.replaced,
        summary.failed,
      );
      pendingSummaryRef.current = null;
      queryClient.invalidateQueries({ queryKey: ["role", selectedRoleId] });
    }
  }

  const sortedRoles = useMemo(
    () =>
      (roles ?? []).slice().sort((a, b) =>
        a.display_name.localeCompare(b.display_name, undefined, {
          numeric: true,
          sensitivity: "base",
        }),
      ),
    [roles],
  );

  const filteredRoles = useMemo(
    () =>
      roleFilter
        ? sortedRoles.filter((r) =>
            r.display_name.toLowerCase().includes(roleFilter.toLowerCase()),
          )
        : sortedRoles,
    [sortedRoles, roleFilter],
  );

  if (isLoading)
    return <p className="p-6 text-muted-foreground">{t("secrets.loading")}</p>;

  return (
    <div className="flex flex-col h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Header row: dropdown + action buttons */}
      <div className="flex flex-wrap items-center gap-2 md:gap-3 px-4 py-2.5 border-b bg-muted/30 shrink-0">
        <Select
          value={selectedRoleId ?? ""}
          onValueChange={(value) => {
            if (hasDirty && !window.confirm(t("common.unsaved_changes")))
              return;
            setSelectedRoleId(value || null);
            setSelectedDocId(null);
            setDraftRole(null);
            setDraftDocContent(null);
            setRoleFilter("");
          }}
        >
          <SelectTrigger className="w-40 md:w-56">
            <SelectValue placeholder={t("roles.select_role")} />
          </SelectTrigger>
          <SelectContent>
            <div className="flex items-center gap-1.5 px-2 pb-1.5 border-b mb-1">
              <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <input
                className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                placeholder={t("common.search")}
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                onKeyDown={(e) => e.stopPropagation()}
              />
            </div>
            {filteredRoles.length === 0 ? (
              <div className="px-2 py-3 text-sm text-muted-foreground text-center">
                {t("common.no_results")}
              </div>
            ) : (
              filteredRoles.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.display_name}
                </SelectItem>
              ))
            )}
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
              onSelect={(id) => {
                if (hasDirtyDoc && !window.confirm(t("common.unsaved_changes")))
                  return;
                setDraftDocContent(null);
                setEditingDocName(null);
                setSelectedDocId(id);
                setTab("document");
              }}
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
              onFilesDropped={handleDropFiles}
            />

            {/* Right: main content */}
            <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
              <div className="px-4 md:px-6 py-4 border-b shrink-0">
                <h2 className="text-[18px] font-semibold text-foreground truncate">
                  {currentRole.display_name}
                </h2>
                <p className="text-[12px] text-muted-foreground font-mono mt-0.5">
                  {currentRole.id}
                </p>
                {/* Mobile-only document picker */}
                {allDocuments.length > 0 && (
                  <div className="md:hidden mt-2">
                    <Select
                      value={selectedDocId ?? ""}
                      onValueChange={(v) => {
                        if (v) {
                          setDraftDocContent(null);
                          setSelectedDocId(v);
                          setTab("document");
                        }
                      }}
                    >
                      <SelectTrigger className="w-full h-8 text-[12px]">
                        <SelectValue placeholder={t("roles.select_document")} />
                      </SelectTrigger>
                      <SelectContent>
                        {allDocuments.map((d) => (
                          <SelectItem key={d.id} value={d.id}>
                            <span className="text-[12px]">
                              {d.section} / {d.name}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>

              <div
                className={`flex-1 min-h-0 px-4 md:px-6 py-5 flex flex-col ${tab === "document" ? "" : "overflow-y-auto"}`}
              >
                <Tabs
                  value={tab}
                  onValueChange={(v) => {
                    if (
                      hasDirtyDoc &&
                      v !== "document" &&
                      !window.confirm(t("common.unsaved_changes"))
                    )
                      return;
                    setTab(v as Tab);
                    if (v !== "document") {
                      setDraftDocContent(null);
                      setSelectedDocId(null);
                    }
                  }}
                  className={
                    tab === "document" ? "flex-1 flex flex-col min-h-0" : ""
                  }
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
                        Document
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
                    <TabsContent
                      value="document"
                      className="flex-1 flex flex-col min-h-0"
                    >
                      <div className="flex items-center gap-2 mb-3 shrink-0">
                        {editingDocName !== null ? (
                          <input
                            autoFocus
                            className="text-[15px] font-semibold bg-transparent border-b border-primary outline-none px-0 py-0.5 min-w-[16rem] w-full max-w-md"
                            value={editingDocName}
                            onChange={(e) => setEditingDocName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                const trimmed = editingDocName.trim();
                                if (trimmed && trimmed !== docDisplayName(selectedDoc)) {
                                  const newName = isDocLocked(selectedDoc) ? trimmed + "_" : trimmed;
                                  docMutations.updateDoc.mutate({
                                    docId: selectedDoc.id,
                                    payload: { name: newName },
                                  });
                                }
                                setEditingDocName(null);
                              } else if (e.key === "Escape") {
                                setEditingDocName(null);
                              }
                            }}
                            onBlur={() => {
                              const trimmed = editingDocName.trim();
                              if (trimmed && trimmed !== docDisplayName(selectedDoc)) {
                                const newName = isDocLocked(selectedDoc) ? trimmed + "_" : trimmed;
                                docMutations.updateDoc.mutate({
                                  docId: selectedDoc.id,
                                  payload: { name: newName },
                                });
                              }
                              setEditingDocName(null);
                            }}
                          />
                        ) : (
                          <h3
                            className="text-[15px] font-semibold cursor-pointer hover:text-primary transition-colors min-w-[16rem]"
                            onClick={() => {
                              if (!isDocLocked(selectedDoc)) {
                                setEditingDocName(docDisplayName(selectedDoc));
                              }
                            }}
                          >
                            {docDisplayName(selectedDoc)}
                          </h3>
                        )}
                        {draftDocContent !== null && (
                          <Button
                            size="sm"
                            onClick={handleSaveDocument}
                            className="ml-auto"
                          >
                            <Save className="w-3.5 h-3.5" />
                            {t("roles.save")}
                          </Button>
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
        fields={[{ name: "name", label: t("roles.sidebar.new_document_name") }]}
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
        description={t("roles.confirm_delete_message", {
          name: currentRole?.display_name ?? "",
        })}
        destructive
        onConfirm={handleDeleteRole}
      />

      <ConfirmDialog
        open={deleteSectionTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteSectionTarget(null);
        }}
        title={t("roles.confirm_delete_section_title")}
        description={t("roles.confirm_delete_section_message", {
          name: deleteSectionTarget ?? "",
        })}
        destructive
        onConfirm={handleDeleteSection}
      />

      <DropConflictDialog
        open={conflicts.length > 0}
        name={conflicts[0]?.name ?? ""}
        section={
          pendingSummaryRef.current?.section
            ? (sections.find(
                (s) => s.name === pendingSummaryRef.current?.section,
              )?.display_name ?? "")
            : ""
        }
        suggestedRename={conflicts[0]?.suggestedRename ?? ""}
        onOpenChange={(o) => {
          if (!o) setConflicts([]);
        }}
        onResolve={onResolveConflict}
      />
    </div>
  );
}
