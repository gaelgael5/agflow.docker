import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Monitor, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { useInfraCategories, useInfraCategoryActions } from "@/hooks/useInfra";
import { infraCategoriesApi, type InfraCategory, type InfraCategoryAction } from "@/lib/infraApi";
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
              <TableHead>{t("infra.category_actions")}</TableHead>
              <TableHead className="text-center w-32" title={t("infra.category_visible_in_machines_hint")}>
                <Monitor className="w-3.5 h-3.5 inline-block" />
              </TableHead>
              <TableHead className="text-right w-12">{t("infra.cert_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(categories ?? []).map((c) => (
              <CategoryRowItem
                key={c.name}
                category={c}
                allCategories={(categories ?? []).map((cat) => cat.name)}
                t={t}
              />
            ))}
          </TableBody>
        </Table>
      </Card>

      <AddCategoryDialog
        open={showAddCategory}
        onClose={() => setShowAddCategory(false)}
        onSubmit={async (name) => {
          await infraCategoriesApi.create(name);
          qc.invalidateQueries({ queryKey: ["infra-categories"] });
          setShowAddCategory(false);
          toast.success(t("infra.category_added", { name }));
        }}
        t={t}
      />
    </PageShell>
  );
}

function CategoryRowItem({
  category,
  allCategories,
  t,
}: {
  category: InfraCategory;
  allCategories: string[];
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const { data: actions } = useInfraCategoryActions(category.name);
  const [adding, setAdding] = useState(false);
  const [newAction, setNewAction] = useState("");
  const [newCreatesCategory, setNewCreatesCategory] = useState<string | null>(null);

  const submitAdd = async () => {
    const n = newAction.trim();
    if (!n) return;
    try {
      await infraCategoriesApi.createAction(category.name, n, false, newCreatesCategory);
      qc.invalidateQueries({ queryKey: ["infra-category-actions", category.name] });
      toast.success(t("infra.action_added", { name: n }));
      setNewAction("");
      setNewCreatesCategory(null);
      setAdding(false);
    } catch (e) {
      toast.error(String(e));
    }
  };

  const cancelAdd = () => {
    setAdding(false);
    setNewAction("");
    setNewCreatesCategory(null);
  };

  return (
    <TableRow>
      <TableCell className="font-medium align-top pt-3">{category.name}</TableCell>
      <TableCell>
        <div className="flex flex-wrap items-center gap-1">
          {(actions ?? []).length === 0 && !adding && (
            <span className="text-[11px] text-muted-foreground mr-2">{t("infra.no_actions")}</span>
          )}
          {(actions ?? []).map((a) => (
            <ActionBadge
              key={a.id}
              action={a}
              category={category.name}
              allCategories={allCategories}
              t={t}
              onUpdate={() => qc.invalidateQueries({ queryKey: ["infra-category-actions", category.name] })}
            />
          ))}
          {adding ? (
            <div className="flex flex-wrap items-end gap-1.5 mt-1">
              <div className="space-y-0.5">
                <Label className="text-[10px] text-muted-foreground">{t("infra.action_name")}</Label>
                <Input
                  autoFocus
                  value={newAction}
                  onChange={(e) => setNewAction(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); void submitAdd(); }
                    if (e.key === "Escape") { e.preventDefault(); cancelAdd(); }
                  }}
                  className="h-7 w-36 text-[11px]"
                />
              </div>
              <div className="space-y-0.5">
                <Label className="text-[10px] text-muted-foreground">{t("infra.action_creates_category")}</Label>
                <select
                  className="flex h-7 w-44 rounded-md border border-input bg-background px-2 text-[11px] shadow-sm"
                  value={newCreatesCategory ?? "__none__"}
                  onChange={(e) => setNewCreatesCategory(e.target.value === "__none__" ? null : e.target.value)}
                >
                  <option value="__none__">{t("infra.action_no_creates")}</option>
                  {allCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>
              <Button type="button" size="sm" variant="outline" className="h-7 px-2" onClick={() => void submitAdd()}>
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
      <TableCell className="text-center align-top pt-2">
        <button
          type="button"
          title={t(category.visible_in_machines
            ? "infra.category_visible_on"
            : "infra.category_visible_off")}
          className={`w-8 h-8 rounded-md flex items-center justify-center mx-auto transition-colors ${
            category.visible_in_machines
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "border border-input hover:bg-accent text-muted-foreground"
          }`}
          onClick={async () => {
            try {
              await infraCategoriesApi.setVisibleInMachines(category.name, !category.visible_in_machines);
              qc.invalidateQueries({ queryKey: ["infra-categories"] });
            } catch (e) {
              toast.error(String(e));
            }
          }}
        >
          <Monitor className="w-3.5 h-3.5" />
        </button>
      </TableCell>
      <TableCell className="text-right align-top pt-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={async () => {
            try {
              await infraCategoriesApi.remove(category.name);
              qc.invalidateQueries({ queryKey: ["infra-categories"] });
              toast.success(t("infra.category_removed", { name: category.name }));
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

function ActionBadge({
  action,
  category,
  allCategories,
  t,
  onUpdate,
}: {
  action: InfraCategoryAction;
  category: string;
  allCategories: string[];
  t: (key: string, opts?: Record<string, string>) => string;
  onUpdate: () => void;
}) {
  const qc = useQueryClient();

  return (
    <Badge
      variant={action.is_required ? "default" : "secondary"}
      className={`text-[10px] gap-1 pr-1 ${action.is_required ? "bg-orange-500 hover:bg-orange-600 text-white" : ""}`}
    >
      <button
        type="button"
        title={action.is_required ? t("infra.action_required_on") : t("infra.action_required_off")}
        className="font-medium"
        onClick={async () => {
          try {
            await infraCategoriesApi.updateAction(category, action.name, { is_required: !action.is_required });
            onUpdate();
          } catch (e) {
            toast.error(String(e));
          }
        }}
      >
        {action.is_required ? "★ " : ""}{action.name}
      </button>
      {action.creates_category && (
        <span className="ml-0.5 opacity-75 font-normal">→ {action.creates_category}</span>
      )}
      <select
        title={t("infra.action_creates_category")}
        className="ml-0.5 bg-transparent text-[9px] border-none outline-none cursor-pointer max-w-[80px] truncate"
        style={{ color: "var(--foreground, #111)" }}
        value={action.creates_category ?? "__none__"}
        onChange={async (e) => {
          const v = e.target.value;
          try {
            await infraCategoriesApi.updateAction(category, action.name, {
              creates_category: v === "__none__" ? null : v,
            });
            onUpdate();
          } catch (err) {
            toast.error(String(err));
          }
        }}
      >
        <option value="__none__">—</option>
        {allCategories.map((cat) => (
          <option key={cat} value={cat}>{cat}</option>
        ))}
      </select>
      <button
        type="button"
        className="ml-1 rounded-sm hover:bg-destructive/20"
        onClick={async () => {
          try {
            await infraCategoriesApi.removeAction(category, action.name);
            qc.invalidateQueries({ queryKey: ["infra-category-actions", category] });
            toast.success(t("infra.action_removed", { name: action.name }));
          } catch (e) {
            toast.error(String(e));
          }
        }}
      >
        <X className="w-3 h-3 text-destructive" />
      </button>
    </Badge>
  );
}

function AddCategoryDialog({ open, onClose, onSubmit, t }: {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose(); setName(""); } }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.category_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div>
          <Label className="text-[11px]">{t("infra.category_name")}</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1"
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit(name.trim());
                setName("");
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
