import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useInfraTypes } from "@/hooks/useInfra";
import { infraPlatformsApi, infraServicesApi, infraTypesApi } from "@/lib/infraApi";
import type { PlatformDef, ServiceDef, PlatformCreatePayload, ServiceCreatePayload, InfraType } from "@/lib/infraApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

export function InfraTypesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: types, isLoading } = useInfraTypes();
  const platformsQuery = useQuery({ queryKey: ["infra-platforms"], queryFn: () => infraPlatformsApi.list() });
  const servicesQuery = useQuery({ queryKey: ["infra-services"], queryFn: () => infraServicesApi.list() });

  const [showAddType, setShowAddType] = useState(false);
  const [showAddPlatform, setShowAddPlatform] = useState(false);
  const [showAddService, setShowAddService] = useState(false);
  const [deletePlatform, setDeletePlatform] = useState<string | null>(null);
  const [deleteService, setDeleteService] = useState<string | null>(null);
  const [editPlatform, setEditPlatform] = useState<PlatformDef | null>(null);
  const [editService, setEditService] = useState<ServiceDef | null>(null);

  const platforms = platformsQuery.data ?? [];
  const services = servicesQuery.data ?? [];
  const platformTypes = (types ?? []).filter((t) => t.type === "platform");
  const serviceTypes = (types ?? []).filter((t) => t.type === "service");

  return (
    <PageShell>
      <PageHeader
        title={t("infra.types_title")}
        subtitle={t("infra.types_subtitle")}
        actions={
          <div className="flex gap-2">
            <Button onClick={() => setShowAddType(true)}>
              <Plus className="w-4 h-4" />
              {t("infra.type_add")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                const result = await infraTypesApi.reload();
                toast.success(`${result.platforms} platform(s), ${result.services} service(s)`);
                platformsQuery.refetch();
                servicesQuery.refetch();
              }}
            >
              <RefreshCw className="w-3.5 h-3.5" />
              {t("infra.reload")}
            </Button>
          </div>
        }
      />

      {/* Types table */}
      <Card className="overflow-hidden mb-4">
        {isLoading ? (
          <div className="p-6 space-y-3"><Skeleton className="h-6 w-1/3" /></div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("infra.type_name")}</TableHead>
                <TableHead>{t("infra.type_category")}</TableHead>
                <TableHead className="text-right">{t("infra.cert_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(types ?? []).map((tp) => (
                <TableRow key={tp.name}>
                  <TableCell className="font-medium">{tp.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={`text-[10px] ${
                      tp.type === "platform"
                        ? "border-blue-500 text-blue-600"
                        : "border-green-500 text-green-600"
                    }`}>
                      {tp.type}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={async () => {
                        try {
                          await infraTypesApi.remove(tp.name);
                          qc.invalidateQueries({ queryKey: ["infra-types"] });
                          toast.success(`Type "${tp.name}" supprimé`);
                        } catch (e) {
                          toast.error(String(e));
                        }
                      }}
                    >
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* Platforms */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[14px] font-semibold">{t("infra.platforms")}</h3>
        <Button size="sm" variant="outline" onClick={() => setShowAddPlatform(true)}>
          <Plus className="w-3.5 h-3.5" />
          {t("common.add")}
        </Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        {platforms.map((p: PlatformDef) => (
          <Card key={p.name} className="cursor-pointer hover:border-primary/50 transition-colors" onClick={() => setEditPlatform(p)}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{p.name}</span>
                <div className="flex items-center gap-1">
                  <Badge variant="outline" className="text-[9px]">{p.connection}</Badge>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => { e.stopPropagation(); setDeletePlatform(p.name); }}
                  >
                    <Trash2 className="w-3 h-3 text-destructive" />
                  </Button>
                </div>
              </div>
              <p className="text-[12px] text-muted-foreground mb-2">
                {t("infra.produces_service")}: <strong>{p.service}</strong>
              </p>
              {Object.entries(p.scripts).map(([action, urls]) => (
                <div key={action} className="text-[11px] mt-1">
                  <Badge variant="secondary" className="text-[9px] mr-1">{action}</Badge>
                  <span className="text-muted-foreground">{urls.length} script(s)</span>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Services */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[14px] font-semibold">{t("infra.services")}</h3>
        <Button size="sm" variant="outline" onClick={() => setShowAddService(true)}>
          <Plus className="w-3.5 h-3.5" />
          {t("common.add")}
        </Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {services.map((s: ServiceDef) => (
          <Card key={s.name} className="cursor-pointer hover:border-primary/50 transition-colors" onClick={() => setEditService(s)}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold">{s.name}</span>
                <div className="flex items-center gap-1">
                  <Badge variant="outline" className="text-[9px]">{s.connection}</Badge>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => { e.stopPropagation(); setDeleteService(s.name); }}
                  >
                    <Trash2 className="w-3 h-3 text-destructive" />
                  </Button>
                </div>
              </div>
              <p className="text-[12px] text-muted-foreground">
                {s.scripts.length} {t("infra.install_scripts")}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Add type dialog */}
      <AddTypeDialog
        open={showAddType}
        onClose={() => setShowAddType(false)}
        onSubmit={async (name, type) => {
          await infraTypesApi.create(name, type);
          qc.invalidateQueries({ queryKey: ["infra-types"] });
          setShowAddType(false);
          toast.success(`Type "${name}" ajouté`);
        }}
        t={t}
      />

      {/* Add / Edit platform dialog */}
      <PlatformDialog
        open={showAddPlatform || editPlatform !== null}
        initial={editPlatform}
        onClose={() => { setShowAddPlatform(false); setEditPlatform(null); }}
        platformTypes={platformTypes}
        serviceDefs={services}
        onSubmit={async (p) => {
          if (editPlatform) {
            await infraPlatformsApi.update(editPlatform.name, p);
          } else {
            await infraPlatformsApi.create(p);
          }
          qc.invalidateQueries({ queryKey: ["infra-platforms"] });
          setShowAddPlatform(false);
          setEditPlatform(null);
          toast.success(editPlatform ? `Platform "${p.name}" mise à jour` : `Platform "${p.name}" ajoutée`);
        }}
        t={t}
      />

      {/* Add / Edit service dialog */}
      <ServiceDialog
        open={showAddService || editService !== null}
        initial={editService}
        onClose={() => { setShowAddService(false); setEditService(null); }}
        serviceTypes={serviceTypes}
        onSubmit={async (p) => {
          if (editService) {
            await infraServicesApi.update(editService.name, p);
          } else {
            await infraServicesApi.create(p);
          }
          qc.invalidateQueries({ queryKey: ["infra-services"] });
          setShowAddService(false);
          setEditService(null);
          toast.success(editService ? `Service "${p.name}" mis à jour` : `Service "${p.name}" ajouté`);
        }}
        t={t}
      />

      {/* Delete platform confirm */}
      <ConfirmDialog
        open={deletePlatform !== null}
        onOpenChange={(o) => { if (!o) setDeletePlatform(null); }}
        title={t("infra.platform_delete_title")}
        description={t("infra.platform_delete_message", { name: deletePlatform ?? "" })}
        onConfirm={async () => {
          if (deletePlatform) {
            await infraPlatformsApi.remove(deletePlatform);
            qc.invalidateQueries({ queryKey: ["infra-platforms"] });
            toast.success(`Platform "${deletePlatform}" supprimée`);
          }
        }}
      />

      {/* Delete service confirm */}
      <ConfirmDialog
        open={deleteService !== null}
        onOpenChange={(o) => { if (!o) setDeleteService(null); }}
        title={t("infra.service_delete_title")}
        description={t("infra.service_delete_message", { name: deleteService ?? "" })}
        onConfirm={async () => {
          if (deleteService) {
            await infraServicesApi.remove(deleteService);
            qc.invalidateQueries({ queryKey: ["infra-services"] });
            toast.success(`Service "${deleteService}" supprimé`);
          }
        }}
      />
    </PageShell>
  );
}

function AddTypeDialog({ open, onClose, onSubmit, t }: {
  open: boolean;
  onClose: () => void;
  onSubmit: (name: string, type: "platform" | "service") => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"platform" | "service">("platform");
  const [saving, setSaving] = useState(false);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { onClose(); setName(""); } }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.type_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.type_name")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
              autoFocus
            />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.type_category")}</Label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as "platform" | "service")}
              className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm"
            >
              <option value="platform">Platform</option>
              <option value="service">Service</option>
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit(name.trim(), type);
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

/* ── Shared ───────────────────────────────────────────── */

const CONNECTION_TYPES = ["SSH", "API", "Docker", "WinRM"];
const selectClass = "mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm";
const textareaClass = "mt-1 flex w-full rounded-md border border-input bg-background px-3 py-2 text-[12px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function linesToUrls(text: string): string[] {
  return text.split("\n").map((l) => l.trim()).filter(Boolean);
}

function urlsToLines(urls: string[]): string {
  return urls.join("\n");
}

/* ── Platform Dialog (create + edit) ──────────────────── */

function PlatformDialog({ open, initial, onClose, platformTypes, serviceDefs, onSubmit, t }: {
  open: boolean;
  initial: PlatformDef | null;
  onClose: () => void;
  platformTypes: InfraType[];
  serviceDefs: ServiceDef[];
  onSubmit: (p: PlatformCreatePayload) => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [typeVal, setTypeVal] = useState("");
  const [service, setService] = useState("");
  const [connection, setConnection] = useState("SSH");
  const [createScripts, setCreateScripts] = useState("");
  const [destroyScripts, setDestroyScripts] = useState("");
  const [saving, setSaving] = useState(false);

  const isEdit = initial !== null;

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setTypeVal(initial.type ?? "");
      setService(initial.service);
      setConnection(initial.connection);
      setCreateScripts(urlsToLines(initial.scripts.create ?? []));
      setDestroyScripts(urlsToLines(initial.scripts.destroy ?? []));
    } else {
      setName(""); setTypeVal(""); setService(""); setConnection("SSH");
      setCreateScripts(""); setDestroyScripts("");
    }
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canSubmit = name.trim() && service.trim();

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("infra.platform_edit_title") : t("infra.platform_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.type_name")}</Label>
            {isEdit ? (
              <Input value={name} disabled className="mt-1 opacity-60" />
            ) : (
              <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus />
            )}
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_type")}</Label>
            <select value={typeVal} onChange={(e) => setTypeVal(e.target.value)} className={selectClass}>
              <option value="">—</option>
              {platformTypes.map((p) => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.produces_service")}</Label>
            <select value={service} onChange={(e) => setService(e.target.value)} className={selectClass}>
              <option value="">—</option>
              {serviceDefs.map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.connection_type")}</Label>
            <select value={connection} onChange={(e) => setConnection(e.target.value)} className={selectClass}>
              {CONNECTION_TYPES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.create_scripts")}</Label>
            <textarea
              value={createScripts}
              onChange={(e) => setCreateScripts(e.target.value)}
              placeholder="https://… (one URL per line)"
              rows={3}
              className={textareaClass}
            />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.destroy_scripts")}</Label>
            <textarea
              value={destroyScripts}
              onChange={(e) => setDestroyScripts(e.target.value)}
              placeholder="https://… (one URL per line)"
              rows={3}
              className={textareaClass}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!canSubmit || saving}
            onClick={async () => {
              setSaving(true);
              try {
                const scripts: Record<string, string[]> = {};
                const c = linesToUrls(createScripts);
                const d = linesToUrls(destroyScripts);
                if (c.length) scripts.create = c;
                if (d.length) scripts.destroy = d;
                await onSubmit({ name: name.trim(), type: typeVal, service, connection, scripts });
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

/* ── Service Dialog (create + edit) ───────────────────── */

function ServiceDialog({ open, initial, onClose, serviceTypes, onSubmit, t }: {
  open: boolean;
  initial: ServiceDef | null;
  onClose: () => void;
  serviceTypes: InfraType[];
  onSubmit: (p: ServiceCreatePayload) => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [typeVal, setTypeVal] = useState("");
  const [connection, setConnection] = useState("SSH");
  const [scripts, setScripts] = useState("");
  const [saving, setSaving] = useState(false);

  const isEdit = initial !== null;

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name);
      setTypeVal(initial.type ?? "");
      setConnection(initial.connection);
      setScripts(urlsToLines(initial.scripts));
    } else {
      setName(""); setTypeVal(""); setConnection("SSH"); setScripts("");
    }
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("infra.service_edit_title") : t("infra.service_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.type_name")}</Label>
            {isEdit ? (
              <Input value={name} disabled className="mt-1 opacity-60" />
            ) : (
              <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus />
            )}
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_type")}</Label>
            <select value={typeVal} onChange={(e) => setTypeVal(e.target.value)} className={selectClass}>
              <option value="">—</option>
              {serviceTypes.map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.connection_type")}</Label>
            <select value={connection} onChange={(e) => setConnection(e.target.value)} className={selectClass}>
              {CONNECTION_TYPES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.install_scripts_label")}</Label>
            <textarea
              value={scripts}
              onChange={(e) => setScripts(e.target.value)}
              placeholder="https://… (one URL per line)"
              rows={4}
              className={textareaClass}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSubmit({ name: name.trim(), type: typeVal, connection, scripts: linesToUrls(scripts) });
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
