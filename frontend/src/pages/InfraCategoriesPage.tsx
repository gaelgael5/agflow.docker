import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useInfraCategories, useInfraCategoryActions } from "@/hooks/useInfra";
import { infraCategoriesApi, type InfraCategory } from "@/lib/infraApi";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export function InfraCategoriesPage() {
  const { t } = useTranslation();
  const { data: categories } = useInfraCategories();

  const [showAddCategory, setShowAddCategory] = useState(false);
  const qc = useQueryClient();

  return (
    <PageShell>
      <PageHeader
        title={t("infra.categories_title")}
        subtitle={t("infra.categories_subtitle")}
        actions={
          <Button onClick={() => setShowAddCategory(true)}>
            <Plus className="w-4 h-4" />
            {t("infra.category_add")}
          </Button>
        }
      />

      <Card className="overflow-hidden mb-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("infra.category_name")}</TableHead>
              <TableHead className="w-24">{t("infra.category_vps")}</TableHead>
              <TableHead>{t("infra.category_actions")}</TableHead>
              <TableHead className="text-right">{t("infra.cert_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(categories ?? []).map((c) => (
              <CategoryRowItem key={c.name} category={c} t={t} />
            ))}
          </TableBody>
        </Table>
      </Card>

      <AddCategoryDialog
        open={showAddCategory}
        onClose={() => setShowAddCategory(false)}
        onSubmit={async (name, isVps) => {
          await infraCategoriesApi.create(name, isVps);
          qc.invalidateQueries({ queryKey: ["infra-categories"] });
          setShowAddCategory(false);
          toast.success(t("infra.category_added", { name }));
        }}
        t={t}
      />
    </PageShell>
  );
}

function CategoryRowItem({ category, t }: {
  category: InfraCategory;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const { data: actions } = useInfraCategoryActions(category.name);
  const [adding, setAdding] = useState(false);
  const [newAction, setNewAction] = useState("");

  const submitAdd = async () => {
    const n = newAction.trim();
    if (!n) return;
    try {
      await infraCategoriesApi.createAction(category.name, n);
      qc.invalidateQueries({ queryKey: ["infra-category-actions", category.name] });
      toast.success(t("infra.action_added", { name: n }));
      setNewAction("");
      setAdding(false);
    } catch (e) {
      toast.error(String(e));
    }
  };

  const cancelAdd = () => { setAdding(false); setNewAction(""); };

  return (
    <TableRow>
      <TableCell className="font-medium">{category.name}</TableCell>
      <TableCell>
        <input
          type="checkbox"
          checked={category.is_vps}
          onChange={async (e) => {
            try {
              await infraCategoriesApi.setVps(category.name, e.target.checked);
              qc.invalidateQueries({ queryKey: ["infra-categories"] });
            } catch (err) {
              toast.error(String(err));
            }
          }}
          className="h-4 w-4 rounded border-input"
        />
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap items-center gap-1">
          {(actions ?? []).length === 0 && !adding && (
            <span className="text-[11px] text-muted-foreground mr-2">{t("infra.no_actions")}</span>
          )}
          {(actions ?? []).map((a) => (
            <Badge
              key={a.id}
              variant={a.is_required ? "default" : "secondary"}
              className={`text-[10px] gap-1 pr-1 ${a.is_required ? "bg-orange-500 hover:bg-orange-600 text-white" : ""}`}
            >
              <button
                type="button"
                title={a.is_required ? t("infra.action_required_on") : t("infra.action_required_off")}
                className="font-medium"
                onClick={async () => {
                  try {
                    await infraCategoriesApi.setActionRequired(category.name, a.name, !a.is_required);
                    qc.invalidateQueries({ queryKey: ["infra-category-actions", category.name] });
                  } catch (e) {
                    toast.error(String(e));
                  }
                }}
              >
                {a.is_required ? "★ " : ""}{a.name}
              </button>
              <button
                type="button"
                className="ml-1 rounded-sm hover:bg-destructive/20"
                onClick={async () => {
                  try {
                    await infraCategoriesApi.removeAction(category.name, a.name);
                    qc.invalidateQueries({ queryKey: ["infra-category-actions", category.name] });
                    toast.success(t("infra.action_removed", { name: a.name }));
                  } catch (e) {
                    toast.error(String(e));
                  }
                }}
              >
                <X className="w-3 h-3 text-destructive" />
              </button>
            </Badge>
          ))}
          {adding ? (
            <div className="flex items-center gap-1">
              <Input
                autoFocus
                value={newAction}
                onChange={(e) => setNewAction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); submitAdd(); }
                  if (e.key === "Escape") { e.preventDefault(); cancelAdd(); }
                }}
                className="h-7 w-36 text-[11px]"
              />
              <Button type="button" size="sm" variant="outline" className="h-7 px-2" onClick={submitAdd}>
                {t("common.confirm")}
              </Button>
              <Button type="button" size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={cancelAdd}>
                <X className="w-3 h-3" />
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => setAdding(true)}>
              <Plus className="w-3 h-3" />
              {t("infra.action_add")}
            </Button>
          )}
        </div>
      </TableCell>
      <TableCell className="text-right">
        <Button
          variant="ghost"
          size="icon"
          onClick={async () => {
            try {
              await infraCategoriesApi.remove(category.name);
              qc.invalidateQueries({ queryKey: ["infra-categories"] });
              toast.success(`Catégorie "${category.name}" supprimée`);
            } catch (e) {
              toast.error(String(e));
            }
          }}
        >
          <Trash2 className="w-3.5 h-3.5 text-destructive" />
        </Button>
      </TableCell>
    </TableRow>
  );
}

function AddCategoryDialog({ open, onClose, onSubmit, t }: {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string, isVps: boolean) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [name, setName] = useState("");
  const [isVps, setIsVps] = useState(false);
  const [saving, setSaving] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose(); setName(""); setIsVps(false); } }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.category_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.category_name")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
              autoFocus
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="cat-vps"
              checked={isVps}
              onChange={(e) => setIsVps(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <Label htmlFor="cat-vps" className="text-[11px] cursor-pointer">{t("infra.category_vps")}</Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit(name.trim(), isVps);
                setName("");
                setIsVps(false);
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
