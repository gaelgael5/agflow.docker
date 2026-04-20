import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, ChevronDown, ChevronRight, Edit2, Loader2, Play, Plus, Server, Terminal, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  infraPlatformsApi,
  infraServicesApi,
  infraServersApi,
  infraCertificatesApi,
  type ServerCreatePayload,
  type ServerSummary,
  type PlatformDef,
  type ServiceDef,
  type CertificateSummary,
  type ScriptManifest,
  type DockerContainer,
} from "@/lib/infraApi";
import { useInfraTypes } from "@/hooks/useInfra";
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

export function InfraServersPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: types } = useInfraTypes();
  const platformTypes = (types ?? []).filter((tp) => tp.type === "platform");

  const platformsQuery = useQuery({ queryKey: ["infra-platforms"], queryFn: () => infraPlatformsApi.list() });
  const certsQuery = useQuery({ queryKey: ["infra-certificates"], queryFn: () => infraCertificatesApi.list() });
  const servicesQuery = useQuery({ queryKey: ["infra-services"], queryFn: () => infraServicesApi.list() });

  const listQuery = useQuery({
    queryKey: ["infra-servers"],
    queryFn: () => infraServersApi.list(),
  });
  const createMutation = useMutation({
    mutationFn: (p: ServerCreatePayload) => infraServersApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infra-servers"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => infraServersApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infra-servers"] }),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<ServerSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [scriptRun, setScriptRun] = useState<{ serverId: string; serverName: string; scriptUrl: string; action: string } | null>(null);
  const [terminalTarget, setTerminalTarget] = useState<{ name: string; serverId: string } | null>(null);

  const servers = listQuery.data ?? [];
  const platforms = platformsQuery.data ?? [];
  const serviceDefs = servicesQuery.data ?? [];
  const certificates = certsQuery.data ?? [];
  const [healthMap, setHealthMap] = useState<Record<string, string | null>>({});
  const [containersMap, setContainersMap] = useState<Record<string, DockerContainer[]>>({});
  const [expandedServers, setExpandedServers] = useState<Record<string, boolean>>({});

  // Health check all service-type servers on load
  useEffect(() => {
    if (!servers.length || !serviceDefs.length) return;
    for (const s of servers) {
      const isService = serviceDefs.some((sd) => sd.name === s.type || sd.type === s.type);
      if (!isService) continue;
      setHealthMap((prev) => ({ ...prev, [s.id]: null })); // null = checking
      infraServersApi.healthCheck(s.id)
        .then((res) => {
          setHealthMap((prev) => ({ ...prev, [s.id]: res.state }));
          if ((res.healthy && s.status !== "initialized") || (!res.healthy && s.status === "initialized")) {
            qc.invalidateQueries({ queryKey: ["infra-servers"] });
          }
        })
        .catch(() => setHealthMap((prev) => ({ ...prev, [s.id]: "down" })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [servers.length, serviceDefs.length]);

  function toggleContainers(serverId: string) {
    const isExpanded = expandedServers[serverId];
    setExpandedServers((prev) => ({ ...prev, [serverId]: !isExpanded }));
    if (!isExpanded && !containersMap[serverId]) {
      infraServersApi.listContainers(serverId)
        .then((res) => setContainersMap((prev) => ({ ...prev, [serverId]: res.containers })))
        .catch(() => setContainersMap((prev) => ({ ...prev, [serverId]: [] })));
    }
  }

  function getPlatformForType(serverType: string): PlatformDef | undefined {
    return platforms.find((p) => p.name === serverType || p.type === serverType);
  }

  function getServiceForType(serverType: string): ServiceDef | undefined {
    return serviceDefs.find((s) => s.name === serverType || s.type === serverType);
  }

  return (
    <PageShell maxWidth="full">
      <PageHeader
        title={t("infra.servers_title")}
        subtitle={t("infra.servers_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("infra.server_add")}
          </Button>
        }
      />

      {listQuery.isLoading ? (
        <div className="p-6 space-y-3"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-6 w-1/2" /></div>
      ) : (
        <div className="space-y-4">
          {/* Group: parent servers (no parent_id) with their children */}
          {servers.filter((s) => !s.parent_id).map((parent) => {
            const platform = getPlatformForType(parent.type);
            const createScripts = platform?.scripts.create ?? [];
            const destroyScripts = platform?.scripts.destroy ?? [];
            const children = servers.filter((c) => c.parent_id === parent.id);

            return (
              <Card key={parent.id} className="overflow-hidden">
                {/* Parent header */}
                <div className="flex items-center justify-between px-4 py-3 bg-muted/40 border-b">
                  <div className="flex items-center gap-3">
                    <Server className="w-5 h-5 text-muted-foreground" />
                    <div>
                      <div className="font-semibold">{parent.name || parent.host}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <Badge variant="default" className="text-[10px]">{parent.type}</Badge>
                        <code className="text-[11px] font-mono text-muted-foreground">{parent.host}:{parent.port}</code>
                        {parent.username && <span className="text-[11px] text-muted-foreground">{parent.username}</span>}
                        {platform?.service && (
                          <Badge variant="outline" className="text-[9px] border-green-500 text-green-600">{platform.service}</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {createScripts.map((url, i) => (
                      <Button key={`c-${i}`} variant="ghost" size="sm" className="h-7 text-[10px] text-blue-600"
                        onClick={() => setScriptRun({ serverId: parent.id, serverName: parent.name || parent.host, scriptUrl: url, action: "create" })}
                      >
                        <Terminal className="w-3 h-3 mr-1" />{t("infra.action_create")}
                      </Button>
                    ))}
                    {destroyScripts.map((url, i) => (
                      <Button key={`d-${i}`} variant="ghost" size="sm" className="h-7 text-[10px] text-red-600"
                        onClick={() => setScriptRun({ serverId: parent.id, serverName: parent.name || parent.host, scriptUrl: url, action: "destroy" })}
                      >
                        <Terminal className="w-3 h-3 mr-1" />{t("infra.action_destroy")}
                      </Button>
                    ))}
                    <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.test_connection")}
                      onClick={async () => { const r = await infraServersApi.testConnection(parent.id); r.success ? toast.success(r.message) : toast.error(r.message); }}
                    ><Play className="w-3.5 h-3.5 text-green-600" /></Button>
                    {parent.username && (
                      <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.open_terminal")}
                        onClick={() => setTerminalTarget({ name: parent.name || parent.host, serverId: parent.id })}
                      ><Terminal className="w-3.5 h-3.5 text-purple-600" /></Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditTarget(parent)}>
                      <Edit2 className="w-3.5 h-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7"
                      onClick={() => setDeleteTarget({ id: parent.id, name: parent.name || parent.host })}
                    ><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button>
                  </div>
                </div>

                {/* Children table */}
                {children.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-8">{t("infra.server_name_col")}</TableHead>
                        <TableHead>{t("infra.server_host")}</TableHead>
                        <TableHead>{t("infra.server_info")}</TableHead>
                        <TableHead>{t("infra.server_status")}</TableHead>
                        <TableHead>{t("infra.server_auth")}</TableHead>
                        <TableHead className="text-right">{t("infra.cert_actions")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {children.map((s) => {
                        const service = getServiceForType(s.type);
                        const installScripts = service?.scripts ?? [];
                        const state = healthMap[s.id];

                        const containers = containersMap[s.id];
                        const isExpanded = expandedServers[s.id];

                        return (
                          <React.Fragment key={s.id}>
                          <TableRow className="group">
                            <TableCell className="pl-8">
                              <div className="flex items-center gap-2">
                                <button
                                  className="text-muted-foreground hover:text-foreground transition-colors"
                                  onClick={() => toggleContainers(s.id)}
                                >
                                  {expandedServers[s.id]
                                    ? <ChevronDown className="w-3.5 h-3.5" />
                                    : <ChevronRight className="w-3.5 h-3.5" />
                                  }
                                </button>
                                <span className="font-medium">{s.name || s.host}</span>
                                <Badge variant="outline" className="text-[9px]">{s.type}</Badge>
                              </div>
                            </TableCell>
                            <TableCell>
                              <code className="text-[12px] font-mono">{s.host}:{s.port}</code>
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-col gap-0.5 text-[11px]">
                                {s.metadata?.distro && <span className="text-muted-foreground">{s.metadata.distro}</span>}
                                {s.metadata?.ip_type && <Badge variant="outline" className="text-[9px]">{s.metadata.ip_type}</Badge>}
                                {s.metadata?.docker && s.metadata.docker !== "non installe" && <Badge variant="secondary" className="text-[9px]">Docker</Badge>}
                              </div>
                            </TableCell>
                            <TableCell>
                              {(() => {
                                if (state === null) return <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />;
                                if (state === undefined) return <Badge variant="outline" className="text-[9px] border-gray-400 text-gray-500">—</Badge>;
                                const cfg: Record<string, { label: string; color: string }> = {
                                  healthy: { label: t("infra.status_healthy"), color: "bg-green-600 text-white" },
                                  starting: { label: t("infra.status_starting"), color: "bg-yellow-500 text-white" },
                                  ssh_ok: { label: t("infra.status_ssh_ok"), color: "bg-blue-500 text-white" },
                                  down: { label: t("infra.status_down"), color: "bg-red-600 text-white" },
                                };
                                const entry = cfg[state] ?? { label: "DOWN", color: "bg-red-600 text-white" };
                                return <Badge variant="default" className={`text-[9px] ${entry.color}`}>{entry.label}</Badge>;
                              })()}
                            </TableCell>
                            <TableCell>
                              <div className="flex gap-1 text-[11px]">
                                {s.username && <span>{s.username}</span>}
                                {s.has_password && <Badge variant="secondary" className="text-[9px]">pwd</Badge>}
                                {s.certificate_id && <Badge variant="outline" className="text-[9px]">cert</Badge>}
                              </div>
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center justify-end gap-1 flex-wrap">
                                {s.status !== "initialized" && installScripts.map((url, i) => (
                                  <Button key={`i-${i}`} variant="ghost" size="sm" className="h-7 text-[10px] text-green-600"
                                    onClick={() => setScriptRun({ serverId: s.id, serverName: s.name || s.host, scriptUrl: url, action: "install" })}
                                  >
                                    <Terminal className="w-3 h-3 mr-1" />{t("infra.action_install")}
                                  </Button>
                                ))}
                                <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.test_connection")}
                                  onClick={async () => { const r = await infraServersApi.testConnection(s.id); r.success ? toast.success(r.message) : toast.error(r.message); }}
                                ><Play className="w-3.5 h-3.5 text-green-600" /></Button>
                                {s.username && (
                                  <Button variant="ghost" size="icon" className="h-7 w-7" title={t("infra.open_terminal")}
                                    onClick={() => setTerminalTarget({ name: s.name || s.host, serverId: s.id })}
                                  ><Terminal className="w-3.5 h-3.5 text-purple-600" /></Button>
                                )}
                                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditTarget(s)}>
                                  <Edit2 className="w-3.5 h-3.5" />
                                </Button>
                                <Button variant="ghost" size="icon" className="h-7 w-7"
                                  onClick={() => setDeleteTarget({ id: s.id, name: s.name || `${s.host}:${s.port}` })}
                                ><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button>
                              </div>
                            </TableCell>
                          </TableRow>
                          {/* Docker containers sub-rows */}
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
                      })}
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
          })}

          {/* Orphan servers (have parent_id but parent not in list, or legacy) */}
          {servers.filter((s) => s.parent_id && !servers.some((p) => p.id === s.parent_id)).length > 0 && (
            <Card className="overflow-hidden">
              <div className="px-4 py-3 bg-muted/40 border-b">
                <span className="font-semibold text-muted-foreground">{t("infra.orphan_servers")}</span>
              </div>
              <Table>
                <TableBody>
                  {servers.filter((s) => s.parent_id && !servers.some((p) => p.id === s.parent_id)).map((s) => (
                    <TableRow key={s.id}>
                      <TableCell><span className="font-medium">{s.name || s.host}</span></TableCell>
                      <TableCell><code className="text-[12px] font-mono">{s.host}:{s.port}</code></TableCell>
                      <TableCell>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditTarget(s)}>
                          <Edit2 className="w-3.5 h-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7"
                          onClick={() => setDeleteTarget({ id: s.id, name: s.name || s.host })}
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
      <ServerFormDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        platformTypes={platformTypes}
        certificates={certificates}
        onSubmit={async (p) => {
          await createMutation.mutateAsync(p);
          setShowCreate(false);
        }}
        t={t}
      />

      {/* Edit dialog */}
      <ServerFormDialog
        open={editTarget !== null}
        initial={editTarget}
        onClose={() => setEditTarget(null)}
        platformTypes={platformTypes}
        certificates={certificates}
        onSubmit={async (p) => {
          if (!editTarget) return;
          await infraServersApi.update(editTarget.id, p);
          qc.invalidateQueries({ queryKey: ["infra-servers"] });
          setEditTarget(null);
          toast.success(t("infra.server_updated"));
        }}
        t={t}
      />

      {scriptRun && (
        <ScriptRunDialog
          open
          serverId={scriptRun.serverId}
          serverName={scriptRun.serverName}
          scriptUrl={scriptRun.scriptUrl}
          action={scriptRun.action}
          onClose={() => {
            setScriptRun(null);
            qc.invalidateQueries({ queryKey: ["infra-servers"] });
            qc.invalidateQueries({ queryKey: ["infra-certificates"] });
          }}
          t={t}
        />
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("infra.server_delete_title")}
        description={t("infra.server_delete_message", { name: deleteTarget?.name ?? "" })}
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
            return `${proto}//${window.location.host}/api/infra/servers/${terminalTarget.serverId}/shell?token=${encodeURIComponent(jwt)}`;
          })()}
          onClose={() => setTerminalTarget(null)}
        />
      )}
    </PageShell>
  );
}

/* ── Server Form Dialog (create + edit) ───────────────── */

function ServerFormDialog({ open, initial, onClose, platformTypes, certificates, onSubmit, t }: {
  open: boolean;
  initial?: ServerSummary | null;
  onClose: () => void;
  platformTypes: { name: string; type: string }[];
  certificates: CertificateSummary[];
  onSubmit: (p: ServerCreatePayload) => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [typeVal, setTypeVal] = useState("");
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
      setTypeVal(initial.type);
      setHost(initial.host);
      setPort(String(initial.port));
      setUsername(initial.username ?? "");
      setPassword("");
      setCertificateId(initial.certificate_id ?? "");
    } else {
      setName(""); setTypeVal(""); setHost(""); setPort("22");
      setUsername(""); setPassword(""); setCertificateId("");
    }
    setSaving(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const canSubmit = typeVal.trim() && host.trim();

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("infra.server_edit_title") : t("infra.server_dialog_title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.server_name_col")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus placeholder={t("infra.server_name_placeholder")} />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_type")}</Label>
            {isEdit ? (
              <Input value={typeVal} disabled className="mt-1 opacity-60" />
            ) : (
              <select value={typeVal} onChange={(e) => setTypeVal(e.target.value)} className={selectClass}>
                <option value="">—</option>
                {platformTypes.map((tp) => (
                  <option key={tp.name} value={tp.name}>{tp.name}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_host")}</Label>
            <Input value={host} onChange={(e) => setHost(e.target.value)} className="mt-1 font-mono text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_port")}</Label>
            <Input value={port} onChange={(e) => setPort(e.target.value)} className="mt-1 font-mono text-[12px]" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_username")}</Label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_password")}</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1"
              placeholder={isEdit ? t("infra.server_password_unchanged") : ""} />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.server_certificate")}</Label>
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
                type: typeVal,
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

function ScriptRunDialog({ open, serverId, serverName, scriptUrl, action, onClose, t }: {
  open: boolean;
  serverId: string;
  serverName: string;
  scriptUrl: string;
  action: string;
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

  // Auto-scroll terminal
  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [lines]);

  // Fetch manifest on open
  useEffect(() => {
    if (!open) return;
    setManifest(null); setLoading(true); setArgValues({});
    setRunning(false); setStarted(false); setLines([]); setExitCode(null);

    infraServersApi.fetchManifest(scriptUrl)
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

  // Cleanup WS on close
  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  const execute = useCallback(() => {
    if (!manifest) return;

    // Build command preview
    let cmd = manifest.command;
    for (const [k, v] of Object.entries(argValues)) {
      cmd = cmd.replaceAll(`{${k}}`, v);
    }

    setRunning(true);
    setStarted(true);
    setLines([]);
    setExitCode(null);

    // WebSocket URL with JWT token in query param
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const jwt = localStorage.getItem("agflow_token") ?? "";
    const wsUrl = `${proto}//${window.location.host}/api/infra/servers/${serverId}/exec?token=${encodeURIComponent(jwt)}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ script_url: scriptUrl, args: argValues, action }));
    };

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as { type: string; data: string };
      if (msg.type === "exit") {
        setExitCode(parseInt(msg.data));
        setRunning(false);
      } else if (msg.type === "provisioned" || msg.type === "status_changed") {
        // Auto-provisioning or status update — refresh lists
        qc.invalidateQueries({ queryKey: ["infra-servers"] });
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
  }, [manifest, argValues, serverId, scriptUrl]);

  const canRun = manifest && manifest.args.filter((a) => a.required).every((a) => argValues[a.arg]?.trim());

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { wsRef.current?.close(); onClose(); } }}>
      <DialogContent className="sm:max-w-[70vw] max-h-[85vh] flex flex-col" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            <Badge variant={action === "destroy" ? "destructive" : "default"} className="text-[10px] mr-2">{action}</Badge>
            {serverName}
          </DialogTitle>
          <DialogDescription className="text-[11px] font-mono break-all">{scriptUrl}</DialogDescription>
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

              {/* Command preview */}
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
              {/* Terminal output */}
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
              variant={action === "destroy" ? "destructive" : "default"}
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

