import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Clock, Loader2, SkipForward, XCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  type DeploymentSummary,
  type GroupSummary,
  deploymentsApi,
} from "@/lib/projectsApi";
import { infraMachinesApi } from "@/lib/infraApi";

export interface GroupVar {
  name: string;
  value: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  deployment: DeploymentSummary;
  groups: GroupSummary[];
  groupVars: GroupVar[];
  projectId: string;
}

function StepStatusIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 className="h-4 w-4 text-green-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
  if (status === "skipped") return <SkipForward className="h-4 w-4 text-muted-foreground" />;
  return <Clock className="h-4 w-4 text-muted-foreground" />;
}

export function DeployWizardDialog({
  open,
  onClose,
  deployment,
  groups,
  groupVars,
  projectId,
}: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState("config");
  const [localVars, setLocalVars] = useState<Record<string, string>>(() =>
    Object.fromEntries(groupVars.map((v) => [v.name, v.value])),
  );
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [groupServers, setGroupServers] = useState<Record<string, string>>(
    () => deployment.group_servers ?? {},
  );
  const [dep, setDep] = useState<DeploymentSummary>(deployment);
  const [logs, setLogs] = useState<string[]>([]);
  const [selectedStepLog, setSelectedStepLog] = useState<number | null>(null);
  const [isLive, setIsLive] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const { data: machines = [] } = useQuery({
    queryKey: ["infra-machines"],
    queryFn: () => infraMachinesApi.list(),
  });
  const servers = machines.filter((m) => m.parent_id !== null);

  const { data: steps = [] } = useQuery({
    queryKey: ["deployment-before-steps", dep.id],
    queryFn: () => deploymentsApi.getBeforeSteps(dep.id),
    enabled: dep.status !== "draft",
    staleTime: 30_000,
  });

  useEffect(() => {
    setDep(deployment);
  }, [deployment]);

  useEffect(() => {
    if (isLive) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, isLive]);

  useEffect(() => {
    if (!open) {
      esRef.current?.close();
      esRef.current = null;
      setIsLive(false);
    }
  }, [open]);

  const openSSE = (depId: string) => {
    esRef.current?.close();
    const es = deploymentsApi.streamLogs(depId);
    esRef.current = es;
    setIsLive(true);
    setLogs([]);
    setActiveTab("logs");

    es.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as Record<string, unknown>;
        if (event.type === "log") {
          setLogs((prev) => [...prev, String(event.line ?? "")]);
        } else if (
          event.type === "step_complete" ||
          event.type === "before_complete" ||
          event.type === "step_failed"
        ) {
          setIsLive(false);
          es.close();
          void qc.invalidateQueries({ queryKey: ["deployments", projectId] });
          setActiveTab("exec");
        } else if (event.type === "step_start") {
          setLogs((prev) => [...prev, `▶ ${String(event.script ?? "")}`]);
        }
      } catch {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      setIsLive(false);
      es.close();
    };
  };

  const canGenerate =
    dep.status === "draft" && groups.every((g) => !!groupServers[g.id]);

  const handleGenerate = async () => {
    try {
      // Persist server assignment then generate
      await deploymentsApi.update(dep.id, groupServers);
      const updated = await deploymentsApi.generate(dep.id, {}, localVars);
      setDep(updated);
      void qc.invalidateQueries({ queryKey: ["deployments", projectId] });
      setActiveTab("exec");
      toast.success(t("deploy_wizard_generated_ok"));
    } catch {
      toast.error(t("deploy_wizard_generate_error") ?? "Erreur lors de la génération");
    }
  };

  const handleExecuteStep = async () => {
    openSSE(dep.id);
    try {
      await deploymentsApi.executeStep(dep.id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erreur";
      toast.error(msg);
      setIsLive(false);
    }
  };

  const handleRetry = async () => {
    openSSE(dep.id);
    try {
      await deploymentsApi.retryStep(dep.id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erreur";
      toast.error(msg);
      setIsLive(false);
    }
  };

  const handleDeploy = async () => {
    try {
      setDep((d) => ({ ...d, status: "deploying" }));
      const result = await deploymentsApi.deploy(dep.id);
      void qc.invalidateQueries({ queryKey: ["deployments", projectId] });
      if (result.status === "deployed") {
        toast.success(t("deploy_wizard_deployed_ok"));
      } else {
        toast.error(t("deploy_wizard_deployed_fail"));
      }
      setDep((d) => ({ ...d, status: result.status as DeploymentSummary["status"] }));
    } catch {
      toast.error(t("deploy_wizard_deployed_fail"));
    }
  };

  const currentIdx = dep.current_step_index;

  const stepStatus = (idx: number): string => {
    if (idx < currentIdx) return "done";
    if (idx === currentIdx) {
      if (dep.status === "executing_step") return "running";
      if (dep.status === "step_failed") return "failed";
      if (dep.status === "step_complete" || dep.status === "before_complete") return "done";
    }
    return "waiting";
  };

  const canExecute =
    (dep.status === "generated" || dep.status === "step_complete") &&
    currentIdx < steps.length;
  const canRetry = dep.status === "step_failed";
  const canDeploy = dep.status === "before_complete";

  const displayedLogs =
    selectedStepLog !== null
      ? (dep.step_logs.find((s) => s.step_index === selectedStepLog)?.lines ?? [])
      : logs;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="flex max-h-[90vh] flex-col sm:max-w-[960px]">
        <DialogHeader>
          <DialogTitle>{t("deploy_title")}</DialogTitle>
        </DialogHeader>

        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="shrink-0">
            <TabsTrigger value="config">{t("deploy_wizard_tab_config")}</TabsTrigger>
            <TabsTrigger value="exec">{t("deploy_wizard_tab_exec")}</TabsTrigger>
            <TabsTrigger value="logs">{t("deploy_wizard_tab_logs")}</TabsTrigger>
          </TabsList>

          {/* ── Configuration ── */}
          <TabsContent
            value="config"
            className="flex flex-col gap-4 p-1"
          >
            {/* Server assignment per group */}
            <div className="space-y-2">
              <p className="text-sm font-medium">{t("deploy_wizard_servers_title")}</p>
              <div className="grid grid-cols-[1fr_2fr] items-center gap-2">
                {groups.map((g) => (
                  <div key={g.id} className="contents">
                    <Label className="font-medium text-xs">{g.name}</Label>
                    <select
                      value={groupServers[g.id] ?? ""}
                      onChange={(e) =>
                        setGroupServers((prev) => ({ ...prev, [g.id]: e.target.value }))
                      }
                      className="flex h-8 flex-1 rounded-md border border-input bg-background px-3 py-1 text-[12px] font-mono shadow-sm"
                    >
                      <option value="">— {t("projects.select_server")} —</option>
                      {servers.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name || s.host} ({s.host})
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </div>

            {/* Group variables */}
            {groupVars.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">{t("deploy_wizard_group_vars_title")}</p>
                <div className="grid grid-cols-[1fr_2fr] items-center gap-2">
                  {groupVars.map((v) => (
                    <div key={v.name} className="contents">
                      <Label className="font-mono text-xs">{v.name}</Label>
                      <Input
                        value={localVars[v.name] ?? ""}
                        onChange={(e) =>
                          setLocalVars((prev) => ({ ...prev, [v.name]: e.target.value }))
                        }
                        className="h-7 font-mono text-xs"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex justify-end pt-2">
              <Button
                onClick={() => void handleGenerate()}
                disabled={!canGenerate}
              >
                {t("deploy_wizard_next")}
              </Button>
            </div>
          </TabsContent>

          {/* ── Exécution ── */}
          <TabsContent
            value="exec"
            className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-1"
          >
            {steps.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("deploy_wizard_no_steps")}</p>
            )}
            <div className="space-y-2">
              {steps.map((step, idx) => (
                <div key={step.position}>
                  <div
                    className={`flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm ${
                      idx === currentIdx
                        ? "border-primary/40 bg-primary/5"
                        : "border-border"
                    }`}
                    onClick={() => setExpandedStep(expandedStep === idx ? null : idx)}
                  >
                    <StepStatusIcon status={stepStatus(idx)} />
                    <span className="flex-1 font-medium">{step.script_name}</span>
                    <span className="text-xs text-muted-foreground">{step.machine_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {t("deploy_wizard_step_count", { current: String(idx + 1), total: String(steps.length) })}
                    </span>
                  </div>
                  {expandedStep === idx && step.input_variables.length > 0 && (
                    <div className="mt-1 rounded-md border border-border bg-muted/30 px-3 py-2">
                      <p className="mb-1 text-xs font-medium text-muted-foreground">
                        {t("deploy_wizard_step_inputs")}
                      </p>
                      <div className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5">
                        {step.input_variables.map((v) => (
                          <div key={v.name} className="contents">
                            <span className="font-mono text-xs">{v.name}</span>
                            <span className={`text-xs font-medium ${v.resolved ? "text-green-600" : "text-red-500"}`}>
                              {v.resolved ? "✓" : "✗"}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-auto flex justify-end gap-2">
              {canRetry && (
                <Button variant="outline" onClick={() => void handleRetry()}>
                  {t("deploy_wizard_retry")}
                </Button>
              )}
              {canExecute && (
                <Button onClick={() => void handleExecuteStep()}>
                  {t("deploy_wizard_execute")}
                </Button>
              )}
              {canDeploy && (
                <Button onClick={() => void handleDeploy()}>
                  {t("deploy_wizard_deploy")}
                </Button>
              )}
              {steps.length === 0 && dep.status === "generated" && (
                <Button onClick={() => void handleDeploy()}>
                  {t("deploy_wizard_deploy")}
                </Button>
              )}
            </div>
          </TabsContent>

          {/* ── Logs ── */}
          <TabsContent
            value="logs"
            className="flex min-h-0 flex-1 flex-col gap-2 p-1"
          >
            <div className="flex shrink-0 items-center gap-2">
              {dep.step_logs.map((sl) => (
                <Button
                  key={sl.step_index}
                  variant={selectedStepLog === sl.step_index ? "default" : "outline"}
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() => setSelectedStepLog(sl.step_index)}
                >
                  {t("deploy_wizard_step_select", { index: String(sl.step_index + 1) })}
                </Button>
              ))}
              {isLive && (
                <Button
                  variant={selectedStepLog === null ? "default" : "outline"}
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() => setSelectedStepLog(null)}
                >
                  <span className="relative mr-1 flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
                  </span>
                  {t("deploy_wizard_live")}
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs text-zinc-200">
              {displayedLogs.map((line, i) => (
                <div key={i}>{line || " "}</div>
              ))}
              {isLive && selectedStepLog === null && <div ref={logsEndRef} />}
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
