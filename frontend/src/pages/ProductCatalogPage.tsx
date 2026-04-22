import { useEffect, useState } from "react";
import { YamlEditor } from "@/components/YamlEditor";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useProducts } from "@/hooks/useProducts";
import { productsApi, type ProductDetail } from "@/lib/productsApi";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const CATEGORY_COLORS: Record<string, string> = {
  wiki: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  tasks: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  code: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  design: "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400",
  infra: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  other: "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400",
};

export function ProductCatalogPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { products, isLoading, createMutation, deleteMutation } = useProducts();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [draftYaml, setDraftYaml] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    if (!selectedId) { setDetail(null); setDraftYaml(null); return; }
    productsApi.get(selectedId).then((d) => {
      setDetail(d);
      setDraftYaml(null);
    }).catch(() => setDetail(null));
  }, [selectedId]);

  async function handleSaveRecipe() {
    if (!selectedId || draftYaml === null) return;
    setSaving(true);
    try {
      const updated = await productsApi.updateRecipe(selectedId, draftYaml);
      setDetail(updated);
      setDraftYaml(null);
      qc.invalidateQueries({ queryKey: ["products"] });
      toast.success(t("products.recipe_saved"));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  const editorContent = draftYaml ?? detail?.recipe_yaml ?? "";
  const hasChanges = draftYaml !== null;

  return (
    <PageShell>
      <PageHeader
        title={t("products.page_title")}
        subtitle={t("products.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("products.add_button")}
          </Button>
        }
      />

      <div className="flex gap-4 flex-1 min-h-0 overflow-hidden" style={{ height: "calc(100vh - 10rem)" }}>
        {/* Left — product list */}
        <div className="w-64 shrink-0 overflow-y-auto space-y-2">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : (products ?? []).length === 0 ? (
            <p className="text-muted-foreground italic text-[12px] px-2">{t("products.no_products")}</p>
          ) : (
            (products ?? []).map((p) => (
              <Card
                key={p.id}
                className={`cursor-pointer transition-colors ${selectedId === p.id ? "border-primary bg-primary/5" : "hover:bg-secondary/50"}`}
                onClick={() => setSelectedId(p.id)}
              >
                <CardContent className="p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[13px] font-semibold truncate">{p.display_name}</span>
                    <Badge className={`text-[9px] shrink-0 ${CATEGORY_COLORS[p.category] ?? CATEGORY_COLORS.other}`}>
                      {p.category}
                    </Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground truncate">{p.description}</p>
                  <div className="flex gap-1 mt-1.5">
                    {p.config_only && <Badge variant="outline" className="text-[8px]">SaaS</Badge>}
                    {p.has_openapi && <Badge variant="outline" className="text-[8px] border-green-500 text-green-600">API</Badge>}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        {/* Right — YAML editor */}
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
          {detail ? (
            <>
              <div className="flex items-center justify-between mb-2 shrink-0">
                <div>
                  <span className="text-[14px] font-semibold">{detail.display_name}</span>
                  <code className="text-[11px] text-muted-foreground ml-2">{detail.id}</code>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    disabled={!hasChanges || saving}
                    onClick={() => void handleSaveRecipe()}
                  >
                    <Save className="w-3.5 h-3.5" />
                    {saving ? "..." : t("products.save_recipe")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setDeleteTarget({ id: detail.id, name: detail.display_name })}
                  >
                    <Trash2 className="w-3.5 h-3.5 text-destructive" />
                  </Button>
                </div>
              </div>
              <YamlEditor
                value={editorContent}
                onChange={(v) => setDraftYaml(v)}
                className="flex-1"
              />
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground text-[13px]">
              {t("products.select_product")}
            </div>
          )}
        </div>
      </div>

      {/* Create dialog */}
      <PromptDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        title={t("products.dialog_title")}
        fields={[
          { name: "slug", label: t("products.field_filename"), required: true, monospace: true, pattern: /^[a-z0-9][a-z0-9_-]*$/, patternHint: t("products.filename_hint") },
        ]}
        onSubmit={async (values) => {
          const slug = values.slug ?? "";
          await createMutation.mutateAsync({
            slug,
            display_name: slug,
          });
          setShowCreate(false);
          setSelectedId(slug);
        }}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("products.confirm_delete_title")}
        description={t("products.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) {
            await deleteMutation.mutateAsync(deleteTarget.id);
            if (selectedId === deleteTarget.id) { setSelectedId(null); setDetail(null); }
          }
        }}
      />
    </PageShell>
  );
}
