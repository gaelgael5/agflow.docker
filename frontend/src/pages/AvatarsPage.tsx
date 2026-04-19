import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Pencil, Plus, Star, Trash2, Upload, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { useAvatarThemes, useAvatarTheme, useAvatarCharacter, useAvatarMutations } from "@/hooks/useAvatars";
import { avatarsApi } from "@/lib/avatarsApi";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

export function AvatarsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const [selectedTheme, setSelectedTheme] = useState<string | null>(null);
  const [selectedChar, setSelectedChar] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [showNewTheme, setShowNewTheme] = useState(false);
  const [showNewChar, setShowNewChar] = useState(false);
  const [showEditTheme, setShowEditTheme] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ type: "theme" | "character" | "image"; key: string; name: string } | null>(null);

  const themesQuery = useAvatarThemes();
  const themeDetail = useAvatarTheme(selectedTheme);
  const charDetail = useAvatarCharacter(selectedTheme, selectedChar);
  const mutations = useAvatarMutations(selectedTheme);
  const uploadRef = useRef<HTMLInputElement>(null);

  const themes = themesQuery.data ?? [];
  const characters = themeDetail.data?.characters ?? [];
  const images = charDetail.data?.images ?? [];
  const promptPreview = themeDetail.data && charDetail.data
    ? `${themeDetail.data.prompt}\n\nCharacter: **${charDetail.data.display_name}**.\n${charDetail.data.prompt}`
    : null;

  async function handleGenerate() {
    if (!selectedTheme || !selectedChar) return;
    setGenerating(true);
    try {
      await avatarsApi.generateImage(selectedTheme, selectedChar);
      qc.invalidateQueries({ queryKey: ["avatar-char", selectedTheme, selectedChar] });
      qc.invalidateQueries({ queryKey: ["avatar-theme", selectedTheme] });
      qc.invalidateQueries({ queryKey: ["avatar-themes"] });
      toast.success("Image générée");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setGenerating(false);
    }
  }

  async function handleUpload(file: File) {
    if (!selectedTheme || !selectedChar) return;
    try {
      const result = await avatarsApi.uploadImage(selectedTheme, selectedChar, file);
      // Auto-select if it's the first image
      if (images.length === 0) {
        await avatarsApi.selectImage(selectedTheme, selectedChar, result.number);
      }
      await qc.invalidateQueries({ queryKey: ["avatar-char", selectedTheme, selectedChar] });
      await qc.invalidateQueries({ queryKey: ["avatar-theme", selectedTheme] });
      await qc.invalidateQueries({ queryKey: ["avatar-themes"] });
      toast.success("Image uploadée");
    } catch (e) {
      toast.error(`Upload échoué: ${String(e)}`);
    }
  }

  async function handleSelect(n: number) {
    if (!selectedTheme || !selectedChar) return;
    await avatarsApi.selectImage(selectedTheme, selectedChar, n);
    qc.invalidateQueries({ queryKey: ["avatar-char", selectedTheme, selectedChar] });
  }

  async function handleDeleteImage(n: number) {
    if (!selectedTheme || !selectedChar) return;
    await avatarsApi.deleteImage(selectedTheme, selectedChar, n);
    qc.invalidateQueries({ queryKey: ["avatar-char", selectedTheme, selectedChar] });
    qc.invalidateQueries({ queryKey: ["avatar-theme", selectedTheme] });
    qc.invalidateQueries({ queryKey: ["avatar-themes"] });
  }

  return (
    <PageShell>
      <PageHeader
        title={t("avatars.page_title")}
        subtitle={t("avatars.page_subtitle")}
      />

      <div className="flex gap-4 flex-1 min-h-0 overflow-hidden">
        {/* Col 1 — Themes */}
        <div className="w-56 shrink-0 overflow-y-auto space-y-2">
          {themes.length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic px-2">{t("avatars.no_themes")}</p>
          ) : (
            themes.map((th) => (
              <Card
                key={th.slug}
                className={`cursor-pointer transition-colors ${selectedTheme === th.slug ? "border-primary bg-primary/5" : "hover:bg-secondary/50"}`}
                onClick={() => { setSelectedTheme(th.slug); setSelectedChar(null); }}
              >
                <CardContent className="p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-semibold truncate">{th.display_name}</span>
                    <div className="flex items-center gap-0.5 shrink-0">
                      {selectedTheme === th.slug && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={(e) => { e.stopPropagation(); setShowEditTheme(true); }}
                          title={t("avatars.edit_theme")}
                        >
                          <Pencil className="w-3 h-3" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget({ type: "theme", key: th.slug, name: th.display_name }); }}
                      >
                        <Trash2 className="w-3 h-3 text-destructive" />
                      </Button>
                    </div>
                  </div>
                  <div className="flex gap-2 mt-1">
                    <Badge variant="secondary" className="text-[10px]">{th.character_count} pers.</Badge>
                    <Badge variant="outline" className="text-[10px]">{th.image_count} img</Badge>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
          <Button variant="outline" size="sm" className="w-full" onClick={() => setShowNewTheme(true)}>
            <Plus className="w-3.5 h-3.5" />
            {t("avatars.new_theme")}
          </Button>
        </div>

        {/* Col 2 — Characters */}
        <div className="w-72 shrink-0 overflow-y-auto space-y-2">
          {!selectedTheme ? (
            <p className="text-muted-foreground text-[12px] italic px-2">{t("avatars.no_characters")}</p>
          ) : characters.length === 0 ? (
            <p className="text-muted-foreground text-[12px] italic px-2">{t("avatars.no_characters")}</p>
          ) : (
            characters.map((ch) => (
              <Card
                key={ch.slug}
                className={`cursor-pointer transition-colors ${selectedChar === ch.slug ? "border-primary bg-primary/5" : "hover:bg-secondary/50"}`}
                onClick={() => setSelectedChar(ch.slug)}
              >
                <CardContent className="p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      {(ch.selected || ch.image_count > 0) && selectedTheme ? (
                        <AuthImage
                          theme={selectedTheme}
                          char={ch.slug}
                          n={ch.selected ?? 1}
                          alt={ch.display_name}
                          className="w-8 h-8 rounded object-cover shrink-0"
                        />
                      ) : (
                        <div className="w-8 h-8 rounded bg-muted flex items-center justify-center shrink-0">
                          <ImagePlus className="w-4 h-4 text-muted-foreground" />
                        </div>
                      )}
                      <div className="min-w-0">
                        <span className="text-[13px] font-semibold truncate block">{ch.display_name}</span>
                        <span className="text-[11px] text-muted-foreground">{ch.image_count} img</span>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0"
                      onClick={(e) => { e.stopPropagation(); setDeleteTarget({ type: "character", key: ch.slug, name: ch.display_name }); }}
                    >
                      <Trash2 className="w-3 h-3 text-destructive" />
                    </Button>
                  </div>
                  {ch.description && (
                    <p className="text-[11px] text-muted-foreground mt-1 truncate">{ch.description}</p>
                  )}
                </CardContent>
              </Card>
            ))
          )}
          {selectedTheme && (
            <Button variant="outline" size="sm" className="w-full" onClick={() => setShowNewChar(true)}>
              <Plus className="w-3.5 h-3.5" />
              {t("avatars.new_character")}
            </Button>
          )}
        </div>

        {/* Col 3 — Images + prompt preview */}
        <div className="flex-1 min-w-0 overflow-y-auto space-y-4">
          {selectedChar && selectedTheme ? (
            <>
              {/* Action bar */}
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={handleGenerate}
                  disabled={generating}
                >
                  <Wand2 className="w-3.5 h-3.5" />
                  {generating ? t("avatars.generating") : t("avatars.generate")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => uploadRef.current?.click()}
                >
                  <Upload className="w-3.5 h-3.5" />
                  {t("avatars.upload")}
                </Button>
                <input
                  ref={uploadRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleUpload(f);
                    e.target.value = "";
                  }}
                />
              </div>

              {/* Image grid */}
              {images.length === 0 ? (
                <p className="text-muted-foreground text-[12px] italic">{t("avatars.no_images")}</p>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  {images.map((img) => (
                    <div
                      key={img.number}
                      className={`relative group rounded-lg overflow-hidden border-2 transition-colors cursor-pointer ${
                        img.is_selected ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                      }`}
                      onClick={() => void handleSelect(img.number)}
                    >
                      <AuthImage
                        theme={selectedTheme}
                        char={selectedChar}
                        n={img.number}
                        alt={`${selectedChar} #${img.number}`}
                        className="w-full aspect-square object-cover"
                      />
                      {img.is_selected && (
                        <div className="absolute top-1 left-1 bg-primary text-primary-foreground rounded-full p-0.5">
                          <Star className="w-3 h-3 fill-current" />
                        </div>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="absolute top-1 right-1 h-6 w-6 bg-background/80 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDeleteImage(img.number);
                        }}
                      >
                        <Trash2 className="w-3 h-3 text-destructive" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              {/* Prompt preview */}
              {promptPreview && (
                <div>
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                    {t("avatars.prompt_preview")}
                  </span>
                  <Textarea
                    value={promptPreview}
                    readOnly
                    rows={8}
                    className="mt-1 font-mono text-[11px]"
                  />
                </div>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-[12px] italic p-4">
              {t("avatars.no_characters")}
            </p>
          )}
        </div>
      </div>

      {/* New theme dialog */}
      <PromptDialog
        open={showNewTheme}
        title={t("avatars.dialog_new_theme")}
        size="xl"
        fields={[
          { name: "display_name", label: t("avatars.display_name"), required: true },
          { name: "slug", label: t("avatars.slug"), required: true, autoSlugFrom: "display_name", slugSeparator: "-" },
          { name: "description", label: t("avatars.description") },
          { name: "prompt", label: t("avatars.prompt_theme"), multiline: true, required: true },
          { name: "provider", label: t("avatars.provider"), defaultValue: "dall-e-3", options: [
            { value: "dall-e-3", label: "DALL-E 3" },
          ]},
          { name: "size", label: t("avatars.size"), defaultValue: "1024x1024", options: [
            { value: "1024x1024", label: "1024×1024" },
            { value: "1792x1024", label: "1792×1024 (paysage)" },
            { value: "1024x1792", label: "1024×1792 (portrait)" },
          ]},
          { name: "quality", label: t("avatars.quality"), defaultValue: "hd", options: [
            { value: "hd", label: "HD" },
            { value: "standard", label: "Standard" },
          ]},
          { name: "style", label: t("avatars.style"), defaultValue: "vivid", options: [
            { value: "vivid", label: "Vivid" },
            { value: "natural", label: "Natural" },
          ]},
        ]}
        onSubmit={async (values) => {
          await mutations.createTheme.mutateAsync({
            slug: values.slug ?? "",
            display_name: values.display_name ?? "",
            description: values.description ?? "",
            prompt: values.prompt ?? "",
            provider: values.provider ?? "dall-e-3",
            size: values.size ?? "1024x1024",
            quality: values.quality ?? "hd",
            style: values.style ?? "vivid",
          });
          setShowNewTheme(false);
          setSelectedTheme(values.slug ?? null);
        }}
        onOpenChange={(o) => { if (!o) setShowNewTheme(false); }}
      />

      {/* New character dialog */}
      <PromptDialog
        open={showNewChar}
        title={t("avatars.dialog_new_character")}
        size="lg"
        fields={[
          { name: "display_name", label: t("avatars.display_name"), required: true },
          { name: "slug", label: t("avatars.slug"), required: true, autoSlugFrom: "display_name", slugSeparator: "-" },
          { name: "prompt", label: t("avatars.prompt_character"), multiline: true, required: true },
        ]}
        onSubmit={async (values) => {
          await mutations.createCharacter.mutateAsync({
            slug: values.slug ?? "",
            display_name: values.display_name ?? "",
            description: values.description ?? "",
            prompt: values.prompt ?? "",
          });
          setShowNewChar(false);
          setSelectedChar(values.slug ?? null);
        }}
        onOpenChange={(o) => { if (!o) setShowNewChar(false); }}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={deleteTarget?.type === "theme" ? t("avatars.delete_theme") : t("avatars.delete_character")}
        description={
          deleteTarget?.type === "theme"
            ? t("avatars.confirm_delete_theme", { name: deleteTarget.name })
            : t("avatars.confirm_delete_character", { name: deleteTarget?.name ?? "" })
        }
        onConfirm={async () => {
          if (!deleteTarget) return;
          if (deleteTarget.type === "theme") {
            await mutations.deleteTheme.mutateAsync(deleteTarget.key);
            if (selectedTheme === deleteTarget.key) {
              setSelectedTheme(null);
              setSelectedChar(null);
            }
          } else if (deleteTarget.type === "character" && selectedTheme) {
            await mutations.deleteCharacter.mutateAsync(deleteTarget.key);
            if (selectedChar === deleteTarget.key) setSelectedChar(null);
          }
        }}
      />
      {/* Edit theme dialog */}
      {showEditTheme && themeDetail.data && (
        <EditThemeDialog
          theme={themeDetail.data}
          onClose={() => setShowEditTheme(false)}
          onSave={async (updates) => {
            await avatarsApi.updateTheme(themeDetail.data!.slug, updates);
            qc.invalidateQueries({ queryKey: ["avatar-theme", selectedTheme] });
            qc.invalidateQueries({ queryKey: ["avatar-themes"] });
            setShowEditTheme(false);
          }}
          t={t}
        />
      )}
    </PageShell>
  );
}

function EditThemeDialog({ theme, onClose, onSave, t }: {
  theme: { slug: string; display_name: string; description: string; prompt: string; provider: string; size: string; quality: string; style: string };
  onClose: () => void;
  onSave: (updates: Record<string, string>) => Promise<void>;
  t: (key: string) => string;
}) {
  const [displayName, setDisplayName] = useState(theme.display_name);
  const [description, setDescription] = useState(theme.description);
  const [prompt, setPrompt] = useState(theme.prompt);
  const [saving, setSaving] = useState(false);

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-xl sm:max-h-[85vh] flex flex-col overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("avatars.edit_theme")} — {theme.slug}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("avatars.display_name")}</Label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1 text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("avatars.description")}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1 text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("avatars.prompt_theme")}</Label>
            <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={10} className="mt-1 font-mono text-[11px]" />
          </div>
        </div>
        <DialogFooter className="mt-3">
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={saving || !displayName || !prompt}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave({ display_name: displayName, description, prompt });
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? "..." : t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AuthImage({ theme, char, n, alt, className }: {
  theme: string;
  char: string;
  n: number;
  alt: string;
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    let revoke: string | null = null;
    avatarsApi.fetchImageBlob(theme, char, n).then((url) => {
      revoke = url;
      setSrc(url);
    }).catch(() => setSrc(null));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [theme, char, n]);

  if (!src) return <div className={`bg-muted animate-pulse ${className ?? ""}`} />;
  return <img src={src} alt={alt} className={className} />;
}
