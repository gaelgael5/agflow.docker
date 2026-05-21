import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Edit2, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import {
  useInfraCategories,
  useInfraCategoryActions,
  useInfraNamedTypes,
  useInfraNamedTypeActions,
  useNamedTypeRules,
  useRuntimeConfig,
} from "@/hooks/useInfra";
import {
  infraNamedTypeActionsApi,
  infraNamedTypeRulesApi,
  infraNamedTypesApi,
  type InfraCategory,
  type InfraNamedType,
  type InfraNamedTypeCreatePayload,
} from "@/lib/infraApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { NamedTypeEnvVarsSection } from "@/components/NamedTypeEnvVarsSection";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const CONNECTION_TYPES = ["SSH", "API", "Docker", "WinRM"];

const selectClass = "mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm";

export function InfraNamedTypesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: namedTypes, isLoading } = useInfraNamedTypes();
  const { data: categories } = useInfraCategories();

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<InfraNamedType | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<InfraNamedType | null>(null);

  return (
    <PageShell>
      <PageHeader
        title={t("infra.named_types_title")}
        subtitle={t("infra.named_types_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("infra.named_type_add")}
          </Button>
        }
      />

      {isLoading ? (
        <p className="text-muted-foreground text-sm">…</p>
      ) : (namedTypes ?? []).length === 0 ? (
        <p className="text-muted-foreground text-sm italic">{t("infra.named_types_empty")}</p>
      ) : (
        <NamedTypesByCategory
          namedTypes={namedTypes ?? []}
          categories={categories ?? []}
          onEdit={(nt) => setEditTarget(nt)}
          onDelete={(nt) => setDeleteTarget(nt)}
          t={t}
        />
      )}

      <NamedTypeDialog
        open={showCreate || editTarget !== null}
        initial={editTarget}
        categories={categories ?? []}
        onClose={() => { setShowCreate(false); setEditTarget(null); }}
        onSubmit={async (p, actionUrls) => {
          let namedTypeId: string;
          if (editTarget) {
            const updated = await infraNamedTypesApi.update(editTarget.id, p);
            namedTypeId = updated.id;
          } else {
            const created = await infraNamedTypesApi.create(p);
            namedTypeId = created.id;
          }

          const existing = editTarget
            ? await infraNamedTypeActionsApi.list(namedTypeId)
            : [];
          const existingByCategoryActionId = new Map(
            existing.map((a) => [a.category_action_id, a]),
          );

          for (const [categoryActionId, url] of Object.entries(actionUrls)) {
            const trimmed = url.trim();
            const current = existingByCategoryActionId.get(categoryActionId);
            if (trimmed) {
              if (current) {
                if (current.url !== trimmed) {
                  await infraNamedTypeActionsApi.update(namedTypeId, current.id, { url: trimmed });
                }
              } else {
                await infraNamedTypeActionsApi.create(namedTypeId, categoryActionId, trimmed);
              }
            } else if (current) {
              await infraNamedTypeActionsApi.remove(namedTypeId, current.id);
            }
          }

          qc.invalidateQueries({ queryKey: ["infra-named-types"] });
          qc.invalidateQueries({ queryKey: ["infra-named-type-actions", namedTypeId] });
          setShowCreate(false);
          setEditTarget(null);
          toast.success(editTarget ? t("infra.named_type_updated") : t("infra.named_type_added"));
        }}
        t={t}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("infra.named_type_delete_title")}
        description={t("infra.named_type_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (!deleteTarget) return;
          try {
            await infraNamedTypesApi.remove(deleteTarget.id);
            qc.invalidateQueries({ queryKey: ["infra-named-types"] });
            toast.success(t("infra.named_type_deleted"));
          } catch (e) {
            toast.error(String(e));
          }
        }}
      />
    </PageShell>
  );
}

function NamedTypesByCategory({ namedTypes, categories, onEdit, onDelete, t }: {
  namedTypes: InfraNamedType[];
  categories: InfraCategory[];
  onEdit: (nt: InfraNamedType) => void;
  onDelete: (nt: InfraNamedType) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const visibleSet = new Set(categories.filter((c) => c.visible_in_machines).map((c) => c.name));

  const groups = namedTypes.reduce<Map<string, InfraNamedType[]>>((acc, nt) => {
    const key = nt.type_name || nt.type_id;
    if (!acc.has(key)) acc.set(key, []);
    acc.get(key)!.push(nt);
    return acc;
  }, new Map());

  const sortedEntries = [...groups.entries()].sort(([aKey, aItems], [bKey, bItems]) => {
    const aVisible = visibleSet.has(aItems[0]?.type_id ?? "");
    const bVisible = visibleSet.has(bItems[0]?.type_id ?? "");
    if (aVisible !== bVisible) return aVisible ? -1 : 1;
    return aKey.localeCompare(bKey);
  });

  return (
    <div className="space-y-6">
      {sortedEntries.map(([category, items]) => (
        <div key={category}>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-0.5">
            {category}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {items.map((nt) => (
              <NamedTypeCard
                key={nt.id}
                namedType={nt}
                allNamedTypes={namedTypes}
                onEdit={() => onEdit(nt)}
                onDelete={() => onDelete(nt)}
                t={t}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function NamedTypeCard({ namedType, allNamedTypes, onEdit, onDelete, t }: {
  namedType: InfraNamedType;
  allNamedTypes: InfraNamedType[];
  onEdit: () => void;
  onDelete: () => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const { data: actions } = useInfraNamedTypeActions(namedType.id);

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-semibold">{namedType.name}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <Badge variant="default" className="text-[9px]">{namedType.type_name}</Badge>
              <Badge variant="outline" className="text-[9px]">{namedType.connection_type}</Badge>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onEdit}>
              <Edit2 className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onDelete}>
              <Trash2 className="w-3.5 h-3.5 text-destructive" />
            </Button>
          </div>
        </div>

        <div>
          <Label className="text-[10px] text-muted-foreground">{t("infra.named_type_actions")}</Label>
          <div className="mt-1 space-y-1">
            {(actions ?? []).length === 0 ? (
              <p className="text-[11px] text-muted-foreground italic">{t("infra.named_type_no_actions")}</p>
            ) : (
              (actions ?? []).map((a) => (
                <ActionRow
                  key={a.id}
                  namedTypeId={namedType.id}
                  actionId={a.id}
                  name={a.action_name}
                  url={a.url}
                  createsNamedTypeId={a.creates_named_type_id}
                  allNamedTypes={allNamedTypes}
                  categoryActionId={a.category_action_id}
                  namedTypeCategoryId={namedType.type_id}
                  t={t}
                />
              ))
            )}
            <AddActionButton namedType={namedType} allNamedTypes={allNamedTypes} t={t} />
          </div>
        </div>

        <RulesBlock namedTypeId={namedType.id} t={t} />
      </CardContent>
    </Card>
  );
}

function ActionRow({
  namedTypeId,
  actionId,
  name,
  url,
  createsNamedTypeId,
  allNamedTypes,
  categoryActionId,
  namedTypeCategoryId,
  t,
}: {
  namedTypeId: string;
  actionId: string;
  name: string;
  url: string;
  createsNamedTypeId: string | null;
  allNamedTypes: InfraNamedType[];
  categoryActionId: string;
  namedTypeCategoryId: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(url);

  // Fetch category action to know its creates_category
  const { data: categoryActions } = useInfraCategoryActions(namedTypeCategoryId);
  const categoryAction = (categoryActions ?? []).find((a) => a.id === categoryActionId);
  const createsCategory = categoryAction?.creates_category ?? null;
  const candidateNamedTypes = createsCategory
    ? allNamedTypes.filter((nt) => nt.type_id === createsCategory)
    : [];

  const createsNamedTypeName = createsNamedTypeId
    ? (allNamedTypes.find((nt) => nt.id === createsNamedTypeId)?.name ?? createsNamedTypeId)
    : null;

  const save = async () => {
    const trimmed = val.trim();
    if (!trimmed) return;
    try {
      await infraNamedTypeActionsApi.update(namedTypeId, actionId, { url: trimmed });
      qc.invalidateQueries({ queryKey: ["infra-named-type-actions", namedTypeId] });
      setEditing(false);
      toast.success(t("infra.named_type_action_updated"));
    } catch (e) {
      toast.error(String(e));
    }
  };

  return (
    <div className="space-y-0.5">
      <div className="flex items-start gap-1 text-[11px]">
        <Badge variant="secondary" className="text-[9px] shrink-0">{name}</Badge>
        {editing ? (
          <>
            <Input
              value={val}
              onChange={(e) => setVal(e.target.value)}
              className="h-6 text-[11px] font-mono flex-1"
              autoFocus
            />
            <Button size="sm" variant="outline" className="h-6 px-2 text-[10px]" onClick={save}>OK</Button>
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => { setEditing(false); setVal(url); }}>
              <X className="w-3 h-3" />
            </Button>
          </>
        ) : (
          <>
            <code className="font-mono text-[10px] break-all flex-1">{url}</code>
            <Button variant="ghost" size="icon" className="h-5 w-5 shrink-0" onClick={() => setEditing(true)}>
              <Edit2 className="w-3 h-3" />
            </Button>
            <Button
              variant="ghost" size="icon" className="h-5 w-5 shrink-0"
              onClick={async () => {
                try {
                  await infraNamedTypeActionsApi.remove(namedTypeId, actionId);
                  qc.invalidateQueries({ queryKey: ["infra-named-type-actions", namedTypeId] });
                  toast.success(t("infra.named_type_action_deleted"));
                } catch (e) {
                  toast.error(String(e));
                }
              }}
            >
              <Trash2 className="w-3 h-3 text-destructive" />
            </Button>
          </>
        )}
      </div>
      {/* creates_named_type picker — visible seulement si l'action de catégorie déclare creates_category */}
      {createsCategory && (
        <div className="flex items-center gap-1 pl-1 text-[10px] text-muted-foreground">
          <span className="shrink-0">→ {createsCategory} :</span>
          <select
            className="bg-transparent border border-input rounded px-1 py-0 text-[10px] cursor-pointer"
            value={createsNamedTypeId ?? "__none__"}
            onChange={async (e) => {
              const v = e.target.value;
              try {
                await infraNamedTypeActionsApi.update(namedTypeId, actionId, {
                  creates_named_type_id: v === "__none__" ? null : v,
                });
                qc.invalidateQueries({ queryKey: ["infra-named-type-actions", namedTypeId] });
              } catch (err) {
                toast.error(String(err));
              }
            }}
          >
            <option value="__none__">— {t("common.none")} —</option>
            {candidateNamedTypes.map((nt) => (
              <option key={nt.id} value={nt.id}>{nt.name}</option>
            ))}
          </select>
          {createsNamedTypeName && (
            <span className="text-[9px] opacity-60">{createsNamedTypeName}</span>
          )}
        </div>
      )}
    </div>
  );
}

function AddActionButton({ namedType, allNamedTypes, t }: {
  namedType: InfraNamedType;
  allNamedTypes: InfraNamedType[];
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const { data: categoryActions } = useInfraCategoryActions(namedType.type_id);
  const { data: existing } = useInfraNamedTypeActions(namedType.id);
  const existingActionIds = new Set((existing ?? []).map((a) => a.category_action_id));
  const available = (categoryActions ?? []).filter((a) => !existingActionIds.has(a.id));

  const [open, setOpen] = useState(false);
  const [categoryActionId, setCategoryActionId] = useState("");
  const [url, setUrl] = useState("");
  const [createsNamedTypeId, setCreatesNamedTypeId] = useState<string | null>(null);

  const selectedAction = available.find((a) => a.id === categoryActionId);
  const createsCategory = selectedAction?.creates_category ?? null;
  const candidateNamedTypes = createsCategory
    ? allNamedTypes.filter((nt) => nt.type_id === createsCategory)
    : [];

  useEffect(() => {
    if (open && !categoryActionId && available.length > 0) {
      setCategoryActionId(available[0]!.id);
    }
  }, [open, available, categoryActionId]);

  // Reset creates_named_type_id when the selected action changes
  useEffect(() => {
    setCreatesNamedTypeId(null);
  }, [categoryActionId]);

  if (available.length === 0) return null;

  return (
    <>
      <Button size="sm" variant="outline" className="h-6 text-[10px] mt-1" onClick={() => setOpen(true)}>
        <Plus className="w-3 h-3" />
        {t("infra.named_type_action_add")}
      </Button>
      <Dialog open={open} onOpenChange={(o) => { if (!o) { setOpen(false); setUrl(""); setCreatesNamedTypeId(null); } }}>
        <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{t("infra.named_type_action_add")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-[11px]">{t("infra.category_action_label")}</Label>
              <select value={categoryActionId} onChange={(e) => setCategoryActionId(e.target.value)} className={selectClass}>
                {available.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-[11px]">{t("infra.named_type_action_url")}</Label>
              <Input value={url} onChange={(e) => setUrl(e.target.value)} className="mt-1 font-mono text-[11px]" placeholder="https://..." />
            </div>
            {createsCategory && (
              <div>
                <Label className="text-[11px]">
                  {t("infra.action_creates_named_type_label", { category: createsCategory })}
                </Label>
                <select
                  value={createsNamedTypeId ?? "__none__"}
                  onChange={(e) => setCreatesNamedTypeId(e.target.value === "__none__" ? null : e.target.value)}
                  className={selectClass}
                >
                  <option value="__none__">— {t("common.none")} —</option>
                  {candidateNamedTypes.map((nt) => (
                    <option key={nt.id} value={nt.id}>{nt.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button
              disabled={!categoryActionId || !url.trim()}
              onClick={async () => {
                try {
                  await infraNamedTypeActionsApi.create(
                    namedType.id,
                    categoryActionId,
                    url.trim(),
                    createsNamedTypeId,
                  );
                  qc.invalidateQueries({ queryKey: ["infra-named-type-actions", namedType.id] });
                  setOpen(false);
                  setUrl("");
                  setCreatesNamedTypeId(null);
                  toast.success(t("infra.named_type_action_added"));
                } catch (e) {
                  toast.error(String(e));
                }
              }}
            >
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function RulesBlock({ namedTypeId, t }: {
  namedTypeId: string;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  const { data: rules } = useNamedTypeRules(namedTypeId);
  const { data: runtimeConfig } = useRuntimeConfig();

  const [adding, setAdding] = useState(false);
  const [selectedKey, setSelectedKey] = useState("");
  const [value, setValue] = useState("");

  const configEntries = runtimeConfig ?? [];
  const selectedEntry = configEntries.find((e) => e.key === selectedKey);
  const filterOptions = selectedEntry?.filter ? selectedEntry.filter.split("|") : null;

  const reset = () => { setAdding(false); setSelectedKey(""); setValue(""); };

  const submit = async () => {
    if (!selectedKey || !value) return;
    try {
      await infraNamedTypeRulesApi.create(namedTypeId, selectedKey, value);
      qc.invalidateQueries({ queryKey: ["infra-named-type-rules", namedTypeId] });
      reset();
      toast.success(t("infra.named_type_rule_added"));
    } catch (e) {
      toast.error(String(e));
    }
  };

  return (
    <div className="border-t pt-2 space-y-1.5">
      <Label className="text-[10px] text-muted-foreground">{t("infra.named_type_rules")}</Label>

      {(rules ?? []).length === 0 && !adding && (
        <p className="text-[11px] text-muted-foreground italic">{t("infra.named_type_rules_empty")}</p>
      )}

      {(rules ?? []).map((rule) => (
        <div key={rule.id} className="flex items-center gap-1 text-[11px]">
          <Badge variant="outline" className="text-[9px] font-mono">{rule.key}</Badge>
          <span className="text-muted-foreground">=</span>
          <span className="font-mono text-[10px]">{rule.value}</span>
          <Button
            variant="ghost" size="icon" className="h-4 w-4 ml-auto"
            onClick={async () => {
              try {
                await infraNamedTypeRulesApi.remove(namedTypeId, rule.id);
                qc.invalidateQueries({ queryKey: ["infra-named-type-rules", namedTypeId] });
                toast.success(t("infra.named_type_rule_deleted"));
              } catch (e) {
                toast.error(String(e));
              }
            }}
          >
            <Trash2 className="w-2.5 h-2.5 text-destructive" />
          </Button>
        </div>
      ))}

      {adding ? (
        <div className="flex items-end gap-1">
          <div className="flex-1">
            <select
              value={selectedKey}
              onChange={(e) => { setSelectedKey(e.target.value); setValue(""); }}
              className="flex h-7 w-full rounded-md border border-input bg-background px-2 text-[11px]"
            >
              <option value="">—</option>
              {configEntries.map((e) => (
                <option key={e.key} value={e.key}>{e.key}</option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            {filterOptions ? (
              <select
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="flex h-7 w-full rounded-md border border-input bg-background px-2 text-[11px]"
              >
                <option value="">—</option>
                {filterOptions.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            ) : (
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="h-7 text-[11px]"
                placeholder={t("infra.named_type_rule_value")}
              />
            )}
          </div>
          <Button
            size="sm" variant="outline" className="h-7 px-2 text-[10px]"
            onClick={submit} disabled={!selectedKey || !value}
          >
            OK
          </Button>
          <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={reset}>
            <X className="w-3 h-3" />
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => setAdding(true)}>
          <Plus className="w-3 h-3" />
          {t("infra.named_type_rule_add")}
        </Button>
      )}
    </div>
  );
}

function NamedTypeDialog({ open, initial, categories, onClose, onSubmit, t }: {
  open: boolean;
  initial: InfraNamedType | null;
  categories: InfraCategory[];
  onClose: () => void;
  onSubmit: (p: InfraNamedTypeCreatePayload, actionUrls: Record<string, string>) => Promise<void>;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState("");
  const [connectionType, setConnectionType] = useState("SSH");
  const [actionUrls, setActionUrls] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setTypeId(initial.type_id);
      setConnectionType(initial.connection_type);
    } else {
      setName(""); setTypeId(""); setConnectionType("SSH");
    }
    setActionUrls({});
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const { data: categoryActions } = useInfraCategoryActions(typeId || undefined);
  const { data: existingActions } = useInfraNamedTypeActions(initial?.id);

  useEffect(() => {
    if (!open || !existingActions) return;
    const map: Record<string, string> = {};
    for (const a of existingActions) map[a.category_action_id] = a.url;
    setActionUrls(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingActions, open]);

  const canSubmit = name.trim() && typeId && connectionType;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{initial ? t("infra.named_type_edit_title") : t("infra.named_type_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.named_type_name")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
              autoFocus
              placeholder={t("infra.named_type_name_placeholder")}
            />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.named_type_type_label")}</Label>
            <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className={selectClass}>
              <option value="">—</option>
              {categories.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.connection_type")}</Label>
            <select value={connectionType} onChange={(e) => setConnectionType(e.target.value)} className={selectClass}>
              {CONNECTION_TYPES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          {typeId && (categoryActions ?? []).length > 0 && (
            <div className="space-y-2 border-t pt-3">
              <Label className="text-[11px] font-semibold">
                {t("infra.named_type_category_actions_label", { category: typeId })}
              </Label>
              {(categoryActions ?? []).map((a) => (
                <div key={a.id}>
                  <Label className="text-[10px] text-muted-foreground">{a.name}</Label>
                  <Input
                    value={actionUrls[a.id] ?? ""}
                    onChange={(e) => setActionUrls((prev) => ({ ...prev, [a.id]: e.target.value }))}
                    className="mt-1 font-mono text-[11px]"
                    placeholder="https://... (optionnel)"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        {initial && (
          <div className="border-t pt-4 mt-4">
            <NamedTypeEnvVarsSection namedTypeId={initial.id} />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!canSubmit || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit(
                  {
                    name: name.trim(),
                    type_id: typeId,
                    connection_type: connectionType,
                  },
                  actionUrls,
                );
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
