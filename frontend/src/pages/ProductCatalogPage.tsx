import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useProducts } from "@/hooks/useProducts";
import { productsApi, type ProductDetail } from "@/lib/productsApi";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

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
  const { products, isLoading } = useProducts();
  const [detail, setDetail] = useState<ProductDetail | null>(null);

  async function handleOpenDetail(id: string) {
    const d = await productsApi.get(id);
    setDetail(d);
  }

  return (
    <PageShell>
      <PageHeader
        title={t("products.page_title")}
        subtitle={t("products.page_subtitle")}
      />

      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : (products ?? []).length === 0 ? (
        <p className="text-muted-foreground italic">{t("products.no_products")}</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(products ?? []).map((p) => (
            <Card
              key={p.id}
              className="cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => void handleOpenDetail(p.id)}
            >
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[14px] font-semibold">{p.display_name}</span>
                  <Badge className={`text-[10px] ${CATEGORY_COLORS[p.category] ?? CATEGORY_COLORS.other}`}>
                    {p.category}
                  </Badge>
                </div>
                <p className="text-[12px] text-muted-foreground mb-2">{p.description}</p>
                <div className="flex flex-wrap gap-1">
                  {p.config_only && <Badge variant="outline" className="text-[9px]">{t("products.config_only")}</Badge>}
                  {p.has_openapi && <Badge variant="outline" className="text-[9px] border-green-500 text-green-600">{t("products.has_api")}</Badge>}
                  {p.tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-[9px]">{tag}</Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Detail dialog */}
      <Dialog open={detail !== null} onOpenChange={(o) => { if (!o) setDetail(null); }}>
        <DialogContent className="sm:max-w-3xl sm:max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{detail ? t("products.detail_title", { name: detail.display_name }) : ""}</DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="space-y-4">
              <p className="text-[13px] text-muted-foreground">{detail.description}</p>

              {Array.isArray(detail.recipe.services) && (
                <div>
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase">{t("products.services")}</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(detail.recipe.services as Array<{ id: string; image: string }>).map((s) => (
                      <Badge key={s.id} variant="secondary" className="text-[10px] font-mono">{s.id}: {s.image}</Badge>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(detail.recipe.secrets_required) && (
                <div>
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase">{t("products.secrets")}</span>
                  <ul className="mt-1 space-y-0.5">
                    {(detail.recipe.secrets_required as Array<{ name: string; description: string }>).map((s) => (
                      <li key={s.name} className="text-[12px]">
                        <code className="font-mono text-[11px] text-primary">{s.name}</code>
                        <span className="text-muted-foreground ml-2">— {s.description}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {Array.isArray(detail.recipe.variables) && (
                <div>
                  <span className="text-[11px] font-semibold text-muted-foreground uppercase">{t("products.variables")}</span>
                  <ul className="mt-1 space-y-0.5">
                    {(detail.recipe.variables as Array<{ name: string; description: string; required?: boolean; example?: string }>).map((v) => (
                      <li key={v.name} className="text-[12px]">
                        <code className="font-mono text-[11px] text-primary">{v.name}</code>
                        {v.required && <Badge variant="destructive" className="text-[8px] ml-1">requis</Badge>}
                        <span className="text-muted-foreground ml-2">— {v.description}</span>
                        {v.example && <span className="text-muted-foreground/60 ml-1">(ex: {v.example})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <span className="text-[11px] font-semibold text-muted-foreground uppercase">{t("products.recipe")}</span>
                <pre className="mt-1 bg-muted rounded p-3 text-[11px] font-mono overflow-x-auto max-h-60">
                  {JSON.stringify(detail.recipe, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
