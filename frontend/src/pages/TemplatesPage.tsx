import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { useTemplates } from "@/hooks/useTemplates";
import {
  templatesApi,
  type TemplateDetail,
  type TemplateFileInfo,
} from "@/lib/templatesApi";
import { JinjaEditor } from "@/components/JinjaEditor";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Extract the culture code from a filename like "fr.md.j2" → "fr". */
function extractCulture(filename: string): string {
  const dot = filename.indexOf(".");
  return dot > 0 ? filename.slice(0, dot) : filename;
}

export function TemplatesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { templates, isLoading, createMutation, deleteMutation } =
    useTemplates();

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [draftContent, setDraftContent] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showAddFileDialog, setShowAddFileDialog] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [saving, setSaving] = useState(false);

  const hasUnsavedChanges = draftContent !== null;

  // ── Fetch detail when slug changes ──
  async function fetchDetail(slug: string) {
    const d = await templatesApi.get(slug);
    setDetail(d);
    return d;
  }

  async function handleSelectTemplate(slug: string) {
    setSelectedSlug(slug);
    setSelectedFile(null);
    setFileContent("");
    setDraftContent(null);
    await fetchDetail(slug);
  }

  async function handleSelectFile(filename: string) {
    if (!selectedSlug) return;
    setSelectedFile(filename);
    setDraftContent(null);
    const res = await templatesApi.getFile(selectedSlug, filename);
    setFileContent(res.content);
  }

  const handleSaveFile = useCallback(async () => {
    if (!selectedSlug || !selectedFile || draftContent === null || saving) return;
    setSaving(true);
    try {
      await templatesApi.updateFile(selectedSlug, selectedFile, draftContent);
      setFileContent(draftContent);
      setDraftContent(null);
    } finally {
      setSaving(false);
    }
  }, [selectedSlug, selectedFile, draftContent, saving]);

  async function handleCreateTemplate(values: Record<string, string>) {
    const created = await createMutation.mutateAsync({
      slug: values.slug ?? "",
      display_name: values.display_name ?? "",
      description: values.description ?? "",
    });
    setSelectedSlug(created.slug);
    setSelectedFile(null);
    setFileContent("");
    setDraftContent(null);
    await fetchDetail(created.slug);
  }

  async function handleAddFile(values: Record<string, string>) {
    if (!selectedSlug) return;
    const filename = values.filename ?? "";
    await templatesApi.createFile(selectedSlug, filename, "");
    const d = await fetchDetail(selectedSlug);
    setSelectedFile(filename);
    setFileContent("");
    setDraftContent(null);
    setDetail(d);
  }

  async function handleDeleteTemplate() {
    if (!selectedSlug) return;
    await deleteMutation.mutateAsync(selectedSlug);
    setSelectedSlug(null);
    setDetail(null);
    setSelectedFile(null);
    setFileContent("");
    setDraftContent(null);
  }

  async function handleDeleteFile(filename: string) {
    if (!selectedSlug) return;
    await templatesApi.deleteFile(selectedSlug, filename);
    if (selectedFile === filename) {
      setSelectedFile(null);
      setFileContent("");
      setDraftContent(null);
    }
    await fetchDetail(selectedSlug);
  }

  // ── Ctrl+S shortcut ──
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (hasUnsavedChanges) void handleSaveFile();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  if (isLoading) {
    return <p className="p-6 text-muted-foreground">{t("secrets.loading")}</p>;
  }

  return (
    <div className="flex flex-col h-full min-h-[calc(100vh-3.5rem)] overflow-hidden">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2 md:gap-3 px-4 py-2.5 border-b bg-muted/30 shrink-0">
        <Select
          value={selectedSlug ?? ""}
          onValueChange={(v) => void handleSelectTemplate(v)}
        >
          <SelectTrigger className="w-40 md:w-56">
            <SelectValue placeholder={t("templates.select_template")} />
          </SelectTrigger>
          <SelectContent>
            {(templates ?? []).map((tpl) => (
              <SelectItem key={tpl.slug} value={tpl.slug}>
                <span className="flex items-center gap-2">
                  <span className="truncate">{tpl.display_name}</span>
                  {tpl.cultures.map((c) => (
                    <Badge
                      key={c}
                      variant="secondary"
                      className="text-[10px] px-1 py-0"
                    >
                      {c}
                    </Badge>
                  ))}
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
            title={t("templates.add_button")}
          >
            <Plus className="w-3.5 h-3.5" />
          </Button>
        </div>

        {selectedSlug && detail && (
          <>
            <div className="w-px h-5 bg-border shrink-0" />
            <Button
              size="sm"
              variant="ghost"
              className="text-destructive"
              onClick={() => setShowDeleteConfirm(true)}
            >
              <Trash2 className="w-3.5 h-3.5 mr-1" />
              {t("templates.delete_button")}
            </Button>
          </>
        )}
      </div>

      {/* Body: sidebar + editor */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {selectedSlug && detail ? (
          <>
            {/* Left sidebar: file list */}
            <aside className="w-56 shrink-0 border-r bg-background overflow-y-auto flex flex-col">
              <div key={`${detail.slug}-${detail.display_name}`} className="p-3 border-b space-y-2">
                <input
                  type="text"
                  className="w-full text-[13px] font-semibold bg-transparent border-b border-transparent hover:border-border focus:border-primary outline-none py-0.5 transition-colors"
                  defaultValue={detail.display_name}
                  onBlur={async (e) => {
                    const val = e.target.value.trim();
                    if (val && val !== detail.display_name) {
                      await templatesApi.update(selectedSlug!, { display_name: val });
                      qc.invalidateQueries({ queryKey: ["templates"] });
                      qc.invalidateQueries({ queryKey: ["template", selectedSlug] });
                    }
                  }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                />
                <input
                  type="text"
                  className="w-full text-[11px] text-muted-foreground bg-transparent border-b border-transparent hover:border-border focus:border-primary outline-none py-0.5 transition-colors"
                  defaultValue={detail.description ?? ""}
                  placeholder={t("templates.description_placeholder")}
                  onBlur={async (e) => {
                    const val = e.target.value.trim();
                    if (val !== (detail.description ?? "")) {
                      await templatesApi.update(selectedSlug!, { description: val });
                      qc.invalidateQueries({ queryKey: ["templates"] });
                      qc.invalidateQueries({ queryKey: ["template", selectedSlug] });
                    }
                  }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                />
              </div>

              <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
                {detail.files.length === 0 ? (
                  <p className="text-muted-foreground text-[12px] italic px-2 py-2">
                    {t("templates.no_templates")}
                  </p>
                ) : (
                  detail.files.map((file: TemplateFileInfo) => (
                    <div
                      key={file.filename}
                      className={`flex items-center justify-between gap-1 px-2 py-1.5 rounded-md cursor-pointer transition-colors text-[12px] ${
                        selectedFile === file.filename
                          ? "bg-primary/10 text-primary font-medium"
                          : "text-muted-foreground hover:bg-secondary hover:text-foreground"
                      }`}
                      onClick={() => void handleSelectFile(file.filename)}
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="font-mono truncate">
                          {file.filename}
                        </span>
                        <Badge
                          variant="outline"
                          className="text-[9px] px-1 py-0 shrink-0"
                        >
                          {extractCulture(file.filename)}
                        </Badge>
                      </div>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100 hover:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDeleteFile(file.filename);
                        }}
                        title={t("templates.delete_button")}
                      >
                        <Trash2 className="w-3 h-3 text-destructive" />
                      </Button>
                    </div>
                  ))
                )}
              </div>

              <div className="p-3 border-t">
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full text-[12px]"
                  onClick={() => setShowAddFileDialog(true)}
                >
                  {t("templates.add_file_button")}
                </Button>
              </div>
            </aside>

            {/* Right: editor */}
            <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
              {selectedFile ? (
                <div className="flex-1 flex flex-col min-h-0 px-4 py-3">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <code className="font-mono text-[13px] font-semibold">
                        {selectedFile}
                      </code>
                      <Badge variant="outline" className="text-[10px]">
                        {extractCulture(selectedFile)}
                      </Badge>
                      {hasUnsavedChanges && (
                        <Badge variant="secondary" className="text-[10px]">
                          draft
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {hasUnsavedChanges && (
                        <Button
                          size="sm"
                          onClick={() => void handleSaveFile()}
                          disabled={saving}
                        >
                          <Save className="w-3.5 h-3.5 mr-1" />
                          {t("templates.save")}
                        </Button>
                      )}
                    </div>
                  </div>
                  <JinjaEditor
                    value={draftContent ?? fileContent}
                    onChange={(v) => setDraftContent(v)}
                  />
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted-foreground text-[13px] italic p-6">
                  {t("templates.select_file")}
                </div>
              )}
            </main>
          </>
        ) : (
          <main className="flex-1 flex items-center justify-center text-muted-foreground text-[13px] italic">
            {t("templates.select_template")}
          </main>
        )}
      </div>

      {/* Dialogs */}
      <PromptDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        title={t("templates.new_template_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleCreateTemplate}
        fields={[
          {
            name: "display_name",
            label: t("templates.new_template_name"),
          },
          {
            name: "slug",
            label: t("templates.new_template_slug"),
            autoSlugFrom: "display_name",
            monospace: true,
          },
          {
            name: "description",
            label: t("templates.new_template_description"),
            required: false,
          },
        ]}
      />

      <PromptDialog
        open={showAddFileDialog}
        onOpenChange={setShowAddFileDialog}
        title={t("templates.add_file_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleAddFile}
        fields={[
          {
            name: "filename",
            label: t("templates.add_file_name"),
            placeholder: "fr.md.j2",
            monospace: true,
          },
        ]}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("templates.confirm_delete_title")}
        description={t("templates.confirm_delete_message", {
          name: detail?.display_name ?? selectedSlug ?? "",
        })}
        confirmLabel={t("templates.delete_button")}
        destructive
        onConfirm={handleDeleteTemplate}
      />
    </div>
  );
}
