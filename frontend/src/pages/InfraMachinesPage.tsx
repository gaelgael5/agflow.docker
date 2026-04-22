import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, ChevronDown, ChevronRight, Edit2, History, Loader2, Play, Plus, Server, Terminal, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  infraMachinesApi,
  infraNamedTypeActionsApi,
  infraCertificatesApi,
  type MachineCreatePayload,
  type MachineSummary,
  type InfraNamedType,
  type InfraNamedTypeAction,
  type CertificateSummary,
  type ScriptManifest,
  type DockerContainer,
} from "@/lib/infraApi";
import { useInfraNamedTypes, useInfraMachinesRuns } from "@/hooks/useInfra";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { TerminalWindow } from "@/components/TerminalWindow";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

const selectClass = "mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm";

export function InfraMachinesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: namedTypes } = useInfraNamedTypes();
  const certsQuery = useQuery({ queryKey: ["infra-certificates"], queryFn: () => infraCertificatesApi.list() });
  const listQuery = useQuery({ queryKey: ["infra-machines"], queryFn: () => infraMachinesApi.list() });

  const createMutation = useMutation({
    mutationFn: (p: MachineCreatePayload) => infraMachinesApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infra-machines"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => infraMachinesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infra-machines"] }),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<MachineSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [scriptRun, setScriptRun] = useState<ScriptRunContext | null>(null);
  const [terminalTarget, setTerminalTarget] = useState<{ name: string; machineId: string } | null>(null);
  const [historyTarget, setHistoryTarget] = useState<MachineSummary | null>(null);

  const machines = listQuery.data ?? [];
  const certificates = certsQuery.data ?? [];
  const [healthMap, setHealthMap] = useState<Record<string, string | null>>({});
  const [containersMap, setContainersMap] = useState<Record<string, DockerContainer[]>>({});
  const [expandedMachines, setExpandedMachines] = useState<Record<string, boolean>>({});

  const getNamedType = useCallback(
    (typeId: string): InfraNamedType | undefined => namedTypes?.find((nt) => nt.id === typeId),
    [namedTypes],
  );

  // Health check all service-category machines on load
  useEffect(() => {
    if (!machines.length) return;
    for (const m of machines) {
      if (m.category !== "service") continue;
      setHealthMap((prev) => ({ ...prev, [m.id]: null }));
      infraMachinesApi.healthCheck(m.id)
        .then((res) => {
          setHealthMap((prev) => ({ ...prev, [m.id]: res.state }));
          if ((res.healthy && m.status !== "initialized") || (!res.healthy && m.status === "initialized")) {
            qc.invalidateQueries({ queryKey: ["infra-machines"] });
          }
        })
        .catch(() => setHealthMap((prev) => ({ ...prev, [m.id]: "down" })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [machines.length]);

  function toggleContainers(machineId: string) {
    const isExpanded = expandedMachines[machineId];
    setExpandedMachines((prev) => ({ ...prev, [machineId]: !isExpanded }));
    if (!isExpanded && !containersMap[machineId]) {
      infraMachinesApi.listContainers(machineId)
        .then((res) => setContainersMap((prev) => ({ ...prev, [machineId]: res.containers })))
        .catch(() => setContainersMap((prev) => ({ ...prev, [machineId]: [] })));
    }
  }

  return (
    <PageShell maxWidth="full">
      <PageHeader
        title={t("infra.machines_title")}
        subtitle={t("infra.machines_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("infra.machine_add")}
          </Button>
        }
      />

      {listQuery.isLoading ? (
        <div className="p-6 space-y-3"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-6 w-1/2" /></div>
      ) : (
        <div className="space-y-4">
          {/* Parents (no parent_id) with their children */}
          {machines.filter((m) => !m.parent_id).map((parent) => {
            const parentNamedType = getNamedType(parent.type_id);
            const children = machines.filter((c) => c.parent_id === parent.id);

            return (
              <MachineParentCard
                key={parent.id}
                parent={parent}
                parentNamedType={parentNamedType}
                children={children}
                healthMap={healthMap}
                containersMap={containersMap}
                expandedMachines={expandedMachines}
                onEdit={setEditTarget}
                onDelete={(m) => setDeleteTarget({ id: m.id, name: m.name || m.host })}
                onScriptRun={setScriptRun}
                onToggleContainers={toggleContainers}
                onTerminal={(m) => setTerminalTarget({ name: m.name || m.host, machineId: m.id })}
                onHistory={setHistoryTarget}
                t={t}
              />
            );
          })}

          {/* Orphan machines (have parent_id but parent is gone) */}
          {machines.filter((m) => m.parent_id && !machines.some((p) => p.id === m.parent_id)).length > 0 && (
            <Card className="overflow-hidden">
              <div className="px-4 py-3 bg-muted/40 border-b">
                <span className="font-semibold text-muted-foreground">{t("infra.orphan_machines")}</span>
              </div>
              <Table>
                <TableBody>
                  {machines.filter((m) => m.parent_id && !machines.some((p) => p.id === m.parent_id)).map((m) => (
                    <TableRow key={m.id}>
                      <TableCell><span className="font-medium">{m.name || m.host}</span></TableCell>
                      <TableCell><code className="text-[12px] font-mono">{m.host}:{m.port}</code></TableCell>
                      <TableCell>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditTarget(m)}>
                          <Edit2 className="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setDeleteTarget({ id: m.id, name: m.name || m.host })}
                        ><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </div>
      )}

      {/* Create dialog */}
      <MachineFormDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        namedTypes={namedTypes ?? []}
        certificates={certificates}
        onSubmit={async (p) => {
          await createMutation.mutateAsync(p);
          setShowCreate(false);
        }}
        t={t}
      />

      {/* Edit dialog */}
      <MachineFormDialog
        open={editTarget !== null}
        initial={editTarget}
        onClose={() => setEditTarget(null)}
        namedTypes={namedTypes ?? []}
        certificates={certificates}
        onSubmit={async (p) => {
          if (!editTarget) return;
          await infraMachinesApi.update(editTarget.id, p);
          qc.invalidateQueries({ queryKey: ["infra-machines"] });
          setEditTarget(null);
          toast.success(t("infra.machine_updated"));
        }}
        t={t}
      />

      {scriptRun && (
        <ScriptRunDialog
          open
          ctx={scriptRun}
          onClose={() => {
            setScriptRun(null);
            qc.invalidateQueries({ queryKey: ["infra-machines"] });
            qc.invalidateQueries({ queryKey: ["infra-certificates"] });
            qc.invalidateQueries({ queryKey: ["infra-machines-runs"] });
          }}
          t={t}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("infra.machine_delete_title")}
        description={t("infra.machine_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />

      {/* SSH Terminal */}
      {terminalTarget && (
        <TerminalWindow
          containerName={terminalTarget.name}
          wsUrl={(() => {
            const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
            const jwt = localStorage.getItem("agflow_token") ?? "";
            return `${proto}//${window.location.host}/api/infra/machines/${terminalTarget.machineId}/shell?token=${encodeURIComponent(jwt)}`;
          })()}
          onClose={() => setTerminalTarget(null)}
        />
      )}

      {/* Runs history */}
      {historyTarget && (
        <MachineRunsDialog
          open
          machine={historyTarget}
          onClose={() => setHistoryTarget(null)}
          t={t}
        />
      )}
    </PageShell>
  );
}

/* ── Parent card + children table ──────────────────────── */

type ScriptRunContext = {
  machineId: string;
  machineName: string;
  action: string;
  actionId: string;
  url: string;
};

function MachineParentCard({
  parent, parentNamedType, children, healthMap, containersMap, expandedMachines,
  onEdit, onDelete, onScriptRun, onToggleContainers, onTerminal, onHistory, t,
}: {
  parent: MachineSummary;
  parentNamedType: InfraNamedType | undefined;
  children: MachineSummary[];
  healthMap: Record<string, string | null>;
  containersMap: Record<string, DockerContainer[]>;
  expandedMachines: Record<string, boolean>;
  onEdit: (m: MachineSummary) => void;
  onDelete: (m: MachineSummary) => void;
  onScriptRun: (ctx: ScriptRunContext) => void;
  onToggleContainers: (id: string) => void;
  onTerminal: (m: MachineSummary) => void;
  onHistory: (m: MachineSummary) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const { data: parentActions } = useInfraNamedTypeActions(parent.type_id);
  // All actions except install go in the parent menu (install is for child services).
  const parentMenuActions = (parentActions ?? []).filter((a) => a.action_name !== "install");
  const parentLabel = parent.name || parent.host;

  const actionColor = (actionName: string): string => {
    if (actionName === "create") return "text-blue-600";
    if (actionName === "destroy") return "text-red-600";
    return "";
  };

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-muted/40 border-b">
        <div className="flex items-center gap-3">
          <Server className="w-5 h-5 text-muted-foreground" />
          <div>
            <div className="font-semibold">{parentLabel}</div>
            <div className="flex items-center gap-2 mt-0.5">
              <Badge variant="default" className="text-[10px]">{parent.type_name}</Badge>
              <code className="text-[11px] font-mono text-muted-foreground">{parent.host}:{parent.port}</code>
              {parent.username && <span className="text-[11px] text-muted-foreground">{parent.username}</span>}
              {parentNamedType?.sub_type_name && (
                <Badge variant="outline" className="text-[9px] border-green-500 text-green-600">
                  {parentNamedType.sub_type_name}
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {parentMenuActions.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="h-7 text-[10px]">
                  <Terminal className="w-3 h-3 mr-1" />
                  {t("infra.actions_menu")}
                  <ChevronDown className="w-3 h-3 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-40">
                {parentMenuActions.map((a) => (
                  <DropdownMenuItem
                    key={a.id}
                    className={`text-[11px] ${actionColor(a.action_name)}`}
                    onSelect={() => onScriptRun({
                      machineId: parent.id, machineName: parentLabel,
                      action: a.action_name, actionId: a.id, url: a.url,
                    })}
                  >
                    <Terminal className="w-3 h-3 mr-2" />
                    {a.action_name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <Button
            variant="ghost" size="icon" className="h-7 w-7" title={t("infra.test_connection")}
            onClick={async () => {
              const r = await infraMachinesApi.testConnection(parent.id);
              r.success ? toast.success(r.message) : toast.error(r.message);
            }}
          ><Play className="w-3.5 h-3.5 text-green-600" /></Button>
          {parent.username && (
            <Button
              variant="ghost" size="icon" className="h-7 w-7" title={t("infra.open_terminal")}
              onClick={() => onTerminal(parent)}
            ><Terminal className="w-3.5 h-3.5 text-purple-600" /></Button>
          )}
          <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.runs_history")} onClick={() => onHistory(parent)}>
            <History className="w-3.5 h-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onEdit(parent)}>
            <Edit2 className="w-3.5 h-3.5" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onDelete(parent)}>
            <Trash2 className="w-3.5 h-3.5 text-destructive" />
          </Button>
        </div>
      </div>

      {children.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-8">{t("infra.machine_name_col")}</TableHead>
              <TableHead>{t("infra.machine_host")}</TableHead>
              <TableHead>{t("infra.machine_info")}</TableHead>
              <TableHead>{t("infra.machine_status")}</TableHead>
              <TableHead>{t("infra.machine_auth")}</TableHead>
              <TableHead className="text-right">{t("infra.cert_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {children.map((m) => (
              <MachineChildRow
                key={m.id}
                machine={m}
                health={healthMap[m.id]}
                containers={containersMap[m.id]}
                isExpanded={!!expandedMachines[m.id]}
                onEdit={onEdit}
                onDelete={onDelete}
                onScriptRun={onScriptRun}
                onToggleContainers={onToggleContainers}
                onTerminal={onTerminal}
                onHistory={onHistory}
                t={t}
              />
            ))}
          </TableBody>
        </Table>
      )}

      {children.length === 0 && (
        <div className="px-8 py-4 text-[12px] text-muted-foreground italic">
          {t("infra.no_children")}
        </div>
      )}
    </Card>
  );
}

function MachineChildRow({
  machine, health, containers, isExpanded,
  onEdit, onDelete, onScriptRun, onToggleContainers, onTerminal, onHistory, t,
}: {
  machine: MachineSummary;
  health: string | null | undefined;
  containers: DockerContainer[] | undefined;
  isExpanded: boolean;
  onEdit: (m: MachineSummary) => void;
  onDelete: (m: MachineSummary) => void;
  onScriptRun: (ctx: ScriptRunContext) => void;
  onToggleContainers: (id: string) => void;
  onTerminal: (m: MachineSummary) => void;
  onHistory: (m: MachineSummary) => void;
  t: (key: string, opts?: Record<string, string>) => string;
}) {
  const { data: childActions } = useInfraNamedTypeActions(machine.type_id);
  const childMenuActions = childActions ?? [];
  const machineLabel = machine.name || machine.host;

  const childActionColor = (actionName: string): string => {
    if (actionName === "install") return "text-green-600";
    if (actionName === "destroy") return "text-red-600";
    return "";
  };

  return (
    <React.Fragment>
      <TableRow className="group">
        <TableCell className="pl-8">
          <div className="flex items-center gap-2">
            <button
              className="text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => onToggleContainers(machine.id)}
            >
              {isExpanded
                ? <ChevronDown className="w-3.5 h-3.5" />
                : <ChevronRight className="w-3.5 h-3.5" />
              }
            </button>
            <span className="font-medium">{machineLabel}</span>
            <Badge variant="outline" className="text-[9px]">{machine.type_name}</Badge>
          </div>
        </TableCell>
        <TableCell>
          <code className="text-[12px] font-mono">{machine.host}:{machine.port}</code>
        </TableCell>
        <TableCell>
          <div className="flex flex-col gap-0.5 text-[11px]">
            {machine.metadata?.distro && <span className="text-muted-foreground">{machine.metadata.distro}</span>}
            {machine.metadata?.ip_type && <Badge variant="outline" className="text-[9px]">{machine.metadata.ip_type}</Badge>}
            {machine.metadata?.docker && machine.metadata.docker !== "non installe" && <Badge variant="secondary" className="text-[9px]">Docker</Badge>}
          </div>
        </TableCell>
        <TableCell>
          {(() => {
            if (health === null) return <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />;
            if (health === undefined) return <Badge variant="outline" className="text-[9px] border-gray-400 text-gray-500">—</Badge>;
            const cfg: Record<string, { label: string; color: string }> = {
              healthy: { label: t("infra.status_healthy"), color: "bg-green-600 text-white" },
              starting: { label: t("infra.status_starting"), color: "bg-yellow-500 text-white" },
              ssh_ok: { label: t("infra.status_ssh_ok"), color: "bg-blue-500 text-white" },
              down: { label: t("infra.status_down"), color: "bg-red-600 text-white" },
            };
            const entry = cfg[health] ?? { label: "DOWN", color: "bg-red-600 text-white" };
            return <Badge variant="default" className={`text-[9px] ${entry.color}`}>{entry.label}</Badge>;
          })()}
        </TableCell>
        <TableCell>
          <div className="flex gap-1 text-[11px]">
            {machine.username && <span>{machine.username}</span>}
            {machine.has_password && <Badge variant="secondary" className="text-[9px]">pwd</Badge>}
            {machine.certificate_id && <Badge variant="outline" className="text-[9px]">cert</Badge>}
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center justify-end gap-1 flex-wrap">
            {childMenuActions.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-7 text-[10px]">
                    <Terminal className="w-3 h-3 mr-1" />
                    {t("infra.actions_menu")}
                    <ChevronDown className="w-3 h-3 ml-1" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-40">
                  {childMenuActions.map((a) => (
                    <DropdownMenuItem
                      key={a.id}
                      className={`text-[11px] ${childActionColor(a.action_name)}`}
                      onSelect={() => onScriptRun({
                        machineId: machine.id, machineName: machineLabel,
                        action: a.action_name, actionId: a.id, url: a.url,
                      })}
                    >
                      <Terminal className="w-3 h-3 mr-2" />
                      {a.action_name}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <Button
              variant="ghost" size="icon" className="h-7 w-7" title={t("infra.test_connection")}
              onClick={async () => {
                const r = await infraMachinesApi.testConnection(machine.id);
                r.success ? toast.success(r.message) : toast.error(r.message);
              }}
            ><Play className="w-3.5 h-3.5 text-green-600" /></Button>
            {machine.username && (
              <Button
                variant="ghost" size="icon" className="h-7 w-7" title={t("infra.open_terminal")}
                onClick={() => onTerminal(machine)}
              ><Terminal className="w-3.5 h-3.5 text-purple-600" /></Button>
            )}
            <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.runs_history")} onClick={() => onHistory(machine)}>
              <History className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onEdit(machine)}>
              <Edit2 className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onDelete(machine)}>
              <Trash2 className="w-3.5 h-3.5 text-destructive" />
            </Button>
          </div>
        </TableCell>
      </TableRow>

      {isExpanded && containers && containers.map((c) => (
        <TableRow key={c.id} className="bg-muted/20">
          <TableCell className="pl-16">
            <div className="flex items-center gap-2 text-[11px]">
              <Box className="w-3 h-3 text-muted-foreground" />
              <span className="font-mono">{c.name}</span>
              <Badge
                variant="default"
                className={`text-[8px] ${c.state === "running" ? "bg-green-600" : "bg-zinc-500"} text-white`}
              >
                {c.state}
              </Badge>
            </div>
          </TableCell>
          <TableCell>
            <span className="text-[10px] text-muted-foreground font-mono">{c.image}</span>
          </TableCell>
          <TableCell>
            <span className="text-[10px] text-muted-foreground">{c.status}</span>
          </TableCell>
          <TableCell />
          <TableCell>
            {c.ports && <span className="text-[9px] font-mono text-muted-foreground">{c.ports}</span>}
          </TableCell>
          <TableCell />
        </TableRow>
      ))}
      {isExpanded && containers && containers.length === 0 && (
        <TableRow className="bg-muted/20">
          <TableCell colSpan={6} className="pl-16 text-[11px] text-muted-foreground italic">
            {t("infra.no_containers")}
          </TableCell>
        </TableRow>
      )}
      {isExpanded && !containers && (
        <TableRow className="bg-muted/20">
          <TableCell colSpan={6} className="pl-16">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
          </TableCell>
        </TableRow>
      )}
    </React.Fragment>
  );
}

/* ── Machine Form Dialog (create + edit) ──────────────── */

function MachineFormDialog({ open, initial, onClose, namedTypes, certificates, onSubmit, t }: {
  open: boolean;
  initial?: MachineSummary | null;
  onClose: () => void;
  namedTypes: InfraNamedType[];
  certificates: CertificateSummary[];
  onSubmit: (p: MachineCreatePayload) => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [typeId, setTypeId] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("22");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [certificateId, setCertificateId] = useState("");
  const [saving, setSaving] = useState(false);
  const isEdit = !!initial;

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setName(initial.name || "");
      setTypeId(initial.type_id);
      setHost(initial.host);
      setPort(String(initial.port));
      setUsername(initial.username ?? "");
      setPassword("");
      setCertificateId(initial.certificate_id ?? "");
    } else {
      setName(""); setTypeId(""); setHost(""); setPort("22");
      setUsername(""); setPassword(""); setCertificateId("");
    }
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canSubmit = typeId.trim() && host.trim();

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("infra.machine_edit_title") : t("infra.machine_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.machine_name_col")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus placeholder={t("infra.machine_name_placeholder")} />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_type")}</Label>
            {isEdit ? (
              <Input value={namedTypes.find((nt) => nt.id === typeId)?.name ?? ""} disabled className="mt-1 opacity-60" />
            ) : (
              <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className={selectClass}>
                <option value="">—</option>
                {namedTypes.map((nt) => (
                  <option key={nt.id} value={nt.id}>{nt.name}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_host")}</Label>
            <Input value={host} onChange={(e) => setHost(e.target.value)} className="mt-1 font-mono text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_port")}</Label>
            <Input value={port} onChange={(e) => setPort(e.target.value)} className="mt-1 font-mono text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_username")}</Label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_password")}</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1"
              placeholder={isEdit ? t("infra.machine_password_unchanged") : ""} />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.machine_certificate")}</Label>
            <select value={certificateId} onChange={(e) => setCertificateId(e.target.value)} className={selectClass}>
              <option value="">— {t("common.none")} —</option>
              {certificates.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button disabled={!canSubmit || saving} onClick={async () => {
            setSaving(true);
            try {
              await onSubmit({
                name: name.trim(),
                type_id: typeId,
                host: host.trim(),
                port: parseInt(port || "22", 10),
                username: username || undefined,
                password: password || undefined,
                certificate_id: certificateId || undefined,
              });
            } finally { setSaving(false); }
          }}>
            {saving ? "..." : t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Script Run Dialog (WebSocket streaming) ──────────── */

function useInfraNamedTypeActions(namedTypeId: string | undefined) {
  return useQuery<InfraNamedTypeAction[]>({
    queryKey: ["infra-named-type-actions", namedTypeId ?? ""],
    queryFn: () => infraNamedTypeActionsApi.list(namedTypeId as string),
    enabled: !!namedTypeId,
  });
}

function ScriptRunDialog({ open, ctx, onClose, t }: {
  open: boolean;
  ctx: ScriptRunContext;
  onClose: () => void;
  t: (key: string) => string;
}) {
  const qc = useQueryClient();
  const [manifest, setManifest] = useState<ScriptManifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [argValues, setArgValues] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [started, setStarted] = useState(false);
  const [lines, setLines] = useState<{ type: string; data: string }[]>([]);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const termRef = useRef<HTMLPreElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [lines]);

  useEffect(() => {
    if (!open) return;
    setManifest(null); setLoading(true); setArgValues({});
    setRunning(false); setStarted(false); setLines([]); setExitCode(null);

    infraMachinesApi.fetchManifest(ctx.url)
      .then((m) => {
        setManifest(m);
        const defaults: Record<string, string> = {};
        for (const a of m.args) defaults[a.arg] = a.default != null ? String(a.default) : "";
        setArgValues(defaults);
      })
      .catch((e) => toast.error(String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  const execute = useCallback(() => {
    if (!manifest) return;

    setRunning(true);
    setStarted(true);
    setLines([]);
    setExitCode(null);

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const jwt = localStorage.getItem("agflow_token") ?? "";
    const wsUrl = `${proto}//${window.location.host}/api/infra/machines/${ctx.machineId}/exec?token=${encodeURIComponent(jwt)}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ action_id: ctx.actionId, args: argValues }));
    };

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as { type: string; data: string };
      if (msg.type === "exit") {
        setExitCode(parseInt(msg.data));
        setRunning(false);
      } else if (msg.type === "provisioned" || msg.type === "status_changed") {
        qc.invalidateQueries({ queryKey: ["infra-machines"] });
        qc.invalidateQueries({ queryKey: ["infra-certificates"] });
        setLines((prev) => [...prev, { type: "stdout", data: msg.data + "\n" }]);
      } else if (msg.type === "error") {
        setLines((prev) => [...prev, { type: "stderr", data: msg.data }]);
        setRunning(false);
      } else {
        setLines((prev) => [...prev, msg]);
      }
    };

    ws.onerror = () => {
      setLines((prev) => [...prev, { type: "stderr", data: "WebSocket connection error" }]);
      setRunning(false);
    };

    ws.onclose = () => {
      setRunning(false);
    };
  }, [manifest, argValues, ctx, qc]);

  const canRun = manifest && manifest.args.filter((a) => a.required).every((a) => argValues[a.arg]?.trim());

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { wsRef.current?.close(); onClose(); } }}>
      <DialogContent className="sm:max-w-[70vw] max-h-[85vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            <Badge variant={ctx.action === "destroy" ? "destructive" : "default"} className="text-[10px] mr-2">{ctx.action}</Badge>
            {ctx.machineName}
          </DialogTitle>
          <DialogDescription className="text-[11px] font-mono break-all">{ctx.url}</DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-auto space-y-3">
          {loading ? (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t("infra.script_loading")}
            </div>
          ) : manifest && !started ? (
            <>
              {manifest.args.length > 0 ? (
                <div className="space-y-2">
                  {manifest.args.map((arg) => (
                    <div key={arg.arg}>
                      <Label className="text-[11px]">
                        {arg.label_fr || arg.arg}
                        {arg.required && <span className="text-destructive ml-1">*</span>}
                      </Label>
                      {arg.description_fr && (
                        <p className="text-[10px] text-muted-foreground">{arg.description_fr}</p>
                      )}
                      <Input
                        value={argValues[arg.arg] ?? ""}
                        onChange={(e) => setArgValues((prev) => ({ ...prev, [arg.arg]: e.target.value }))}
                        className="mt-1 font-mono text-[12px]"
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[12px] text-muted-foreground">{t("infra.script_no_args")}</p>
              )}

              {manifest.command && (
                <div>
                  <Label className="text-[10px] text-muted-foreground">{t("infra.script_command_preview")}</Label>
                  <pre className="mt-1 p-2 bg-muted rounded text-[11px] font-mono whitespace-pre-wrap break-all">
                    {(() => {
                      let cmd = manifest.command;
                      for (const [k, v] of Object.entries(argValues)) {
                        cmd = cmd.replaceAll(`{${k}}`, v || `{${k}}`);
                      }
                      return cmd;
                    })()}
                  </pre>
                </div>
              )}
            </>
          ) : started ? (
            <div className="space-y-2">
              <pre
                ref={termRef}
                className="p-3 bg-zinc-950 text-zinc-100 rounded text-[11px] font-mono max-h-[400px] overflow-auto whitespace-pre-wrap leading-5"
              >
                {lines.map((l, i) => (
                  <span key={i} className={l.type === "stderr" ? "text-red-400" : l.type === "cmd" ? "text-yellow-400" : ""}>
                    {l.data.endsWith("\n") ? l.data : l.data + "\n"}
                  </span>
                ))}
                {running && <span className="animate-pulse text-green-400">_</span>}
              </pre>

              {exitCode !== null && (
                <div className="flex items-center gap-2">
                  <Badge variant={exitCode === 0 ? "default" : "destructive"} className="text-[10px]">
                    exit {exitCode}
                  </Badge>
                  {exitCode === 0 && <span className="text-[11px] text-green-600">{t("infra.script_success")}</span>}
                  {exitCode !== 0 && <span className="text-[11px] text-red-600">{t("infra.script_failed")}</span>}
                </div>
              )}
            </div>
          ) : (
            <p className="text-destructive text-sm">{t("infra.script_fetch_error")}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => { wsRef.current?.close(); onClose(); }}>
            {started && !running ? t("common.confirm") : t("common.cancel")}
          </Button>
          {!started && manifest && (
            <Button
              disabled={!canRun || running}
              variant={ctx.action === "destroy" ? "destructive" : "default"}
              onClick={execute}
            >
              <Terminal className="w-4 h-4" />
              {t("infra.script_execute")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Runs History Dialog ──────────────────────────────── */

function MachineRunsDialog({ open, machine, onClose, t }: {
  open: boolean;
  machine: MachineSummary;
  onClose: () => void;
  t: (key: string) => string;
}) {
  const { data: runs, isLoading } = useInfraMachinesRuns(machine.id);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-2xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {t("infra.runs_title")} — {machine.name || machine.host}
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto">
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (runs ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm italic">{t("infra.runs_empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("infra.runs_action")}</TableHead>
                  <TableHead>{t("infra.runs_started")}</TableHead>
                  <TableHead>{t("infra.runs_finished")}</TableHead>
                  <TableHead>{t("infra.runs_result")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs ?? []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell><Badge variant="outline" className="text-[10px]">{r.action_name}</Badge></TableCell>
                    <TableCell className="text-[11px] font-mono">{new Date(r.started_at).toLocaleString()}</TableCell>
                    <TableCell className="text-[11px] font-mono">
                      {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      {r.success === null && <Badge variant="secondary" className="text-[10px]">{t("infra.runs_running")}</Badge>}
                      {r.success === true && <Badge variant="default" className="text-[10px] bg-green-600 text-white">ok</Badge>}
                      {r.success === false && <Badge variant="destructive" className="text-[10px]">fail ({r.exit_code ?? "—"})</Badge>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
