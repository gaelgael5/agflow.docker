import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Play, Plus, RefreshCw, Square, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { useProductInstances } from "@/hooks/useProductInstances";
import { useProducts } from "@/hooks/useProducts";
import { useProjects } from "@/hooks/useProjects";
import { useServiceTypes } from "@/hooks/useServiceTypes";
import { productInstancesApi, type BackendInfo } from "@/lib/productInstancesApi";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  active: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  stopped: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
};

export function ProductInstancesPage() {
  const { t } = useTranslation();
  const { instances, isLoading, createMutation, deleteMutation, activateMutation, stopMutation } = useProductInstances();
  const { products } = useProducts();
  const { projects } = useProjects();
  const { serviceTypes } = useServiceTypes();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ projectId: string; instanceId: string; name: string } | null>(null);
  const [activateTarget, setActivateTarget] = useState<{ projectId: string; instanceId: string } | null>(null);
  const [generating, setGenerating] = useState<string | null>(null);
  const [backendDetail, setBackendDetail] = useState<{ instanceId: string; data: BackendInfo } | null>(null);

  const productName = (catalogId: string) => products?.find((p) => p.id === catalogId)?.display_name ?? catalogId;
  const projectName = (projectId: string) => projects?.find((p) => p.id === projectId)?.display_name ?? projectId;

  return (
    <PageShell>
      <PageHeader
        title={t("instances.page_title")}
        subtitle={t("instances.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("instances.add_button")}
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (instances ?? []).length === 0 ? (
          <p className="text-muted-foreground italic p-6">{t("instances.no_instances")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("instances.col_name")}</TableHead>
                <TableHead>{t("instances.col_product")}</TableHead>
                <TableHead>{t("instances.col_project")}</TableHead>
                <TableHead>{t("instances.col_role")}</TableHead>
                <TableHead>{t("instances.col_status")}</TableHead>
                <TableHead className="text-right">{t("instances.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(instances ?? []).map((inst) => (
                <TableRow key={inst.id}>
                  <TableCell>
                    <span className="font-medium">{inst.instance_name}</span>
                    {inst.service_url && (
                      <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{inst.service_url}</p>
                    )}
                  </TableCell>
                  <TableCell>{productName(inst.catalog_id)}</TableCell>
                  <TableCell>{projectName(inst.project_id)}</TableCell>
                  <TableCell>
                    {inst.service_role ? (
                      <Badge variant="outline" className="text-[10px]">{inst.service_role}</Badge>
                    ) : "—"}
                  </TableCell>
                  <TableCell>
                    <Badge className={`text-[10px] ${STATUS_COLORS[inst.status] ?? ""}`}>
                      {t(`instances.status_${inst.status}`)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {/* Generate + Download */}
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("instances.generate")}
                        disabled={generating === inst.id}
                        onClick={async () => {
                          setGenerating(inst.id);
                          try {
                            const result = await productInstancesApi.generate(inst.project_id, inst.id);
                            toast.success(`${result.artifact_count} fichier(s) généré(s)`);
                          } catch (e) {
                            toast.error(String(e));
                          } finally {
                            setGenerating(null);
                          }
                        }}
                      >
                        <Wand2 className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        title={t("instances.download")}
                        onClick={async () => {
                          try {
                            const blob = await productInstancesApi.downloadZip(inst.project_id, inst.id);
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `${inst.instance_name}-docker_compose.zip`;
                            a.click();
                            URL.revokeObjectURL(url);
                          } catch (e) {
                            toast.error(String(e));
                          }
                        }}
                      >
                        <Download className="w-3.5 h-3.5" />
                      </Button>

                      {/* Activate / Stop */}
                      {(inst.status === "draft" || inst.status === "stopped") && (
                        <Button
                          variant="ghost"
                          size="icon"
                          title={t("instances.activate")}
                          onClick={() => setActivateTarget({ projectId: inst.project_id, instanceId: inst.id })}
                        >
                          <Play className="w-3.5 h-3.5 text-green-600" />
                        </Button>
                      )}
                      {inst.status === "active" && (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("instances.stop")}
                            onClick={async () => {
                              await stopMutation.mutateAsync({ projectId: inst.project_id, instanceId: inst.id });
                              toast.success("Instance arrêtée");
                            }}
                          >
                            <Square className="w-3.5 h-3.5 text-red-600" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            title={t("instances.refresh_openapi")}
                            onClick={async () => {
                              try {
                                await productInstancesApi.refreshOpenapi(inst.project_id, inst.id);
                                toast.success("OpenAPI rafraîchi");
                              } catch (e) {
                                toast.error(String(e));
                              }
                            }}
                          >
                            <RefreshCw className="w-3.5 h-3.5" />
                          </Button>
                        </>
                      )}

                      {/* Backend detail */}
                      {inst.status === "active" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-[11px]"
                          onClick={async () => {
                            const data = await productInstancesApi.getBackend(inst.project_id, inst.id);
                            if (data) setBackendDetail({ instanceId: inst.id, data });
                          }}
                        >
                          {t("instances.backend_detail")}
                        </Button>
                      )}

                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget({ projectId: inst.project_id, instanceId: inst.id, name: inst.instance_name })}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* Create dialog */}
      <PromptDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        title={t("instances.dialog_title")}
        size="lg"
        fields={[
          { name: "instance_name", label: t("instances.field_name"), required: true },
          { name: "instance_slug", label: t("instances.field_slug"), autoSlugFrom: "instance_name", slugSeparator: "-", monospace: true },
          { name: "catalog_id", label: t("instances.field_product"), required: true, options: (products ?? []).map((p) => ({ value: p.id, label: p.display_name })) },
          { name: "project_id", label: t("instances.field_project"), required: true, options: (projects ?? []).map((p) => ({ value: p.id, label: p.display_name })) },
          { name: "service_role", label: t("instances.field_role"), options: [
            { value: "", label: "—" },
            ...(serviceTypes ?? []).map((st) => ({ value: st.name, label: st.display_name })),
          ]},
        ]}
        onSubmit={async (values) => {
          await createMutation.mutateAsync({
            instance_name: values.instance_name ?? "",
            catalog_id: values.catalog_id ?? "",
            project_id: values.project_id ?? "",
            service_role: values.service_role || undefined,
          });
          setShowCreate(false);
        }}
      />

      {/* Activate dialog */}
      <PromptDialog
        open={activateTarget !== null}
        onOpenChange={(o) => { if (!o) setActivateTarget(null); }}
        title={t("instances.activate")}
        fields={[
          { name: "service_url", label: t("instances.activate_url_prompt"), required: true, monospace: true },
        ]}
        onSubmit={async (values) => {
          if (activateTarget) {
            await activateMutation.mutateAsync({
              projectId: activateTarget.projectId,
              instanceId: activateTarget.instanceId,
              serviceUrl: values.service_url ?? "",
            });
            toast.success("Instance activée");
          }
          setActivateTarget(null);
        }}
      />

      {/* Delete confirm */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("instances.confirm_delete_title")}
        description={t("instances.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) {
            await deleteMutation.mutateAsync({ projectId: deleteTarget.projectId, instanceId: deleteTarget.instanceId });
          }
        }}
      />
      {/* Backend detail dialog */}
      <Dialog open={backendDetail !== null} onOpenChange={(o) => { if (!o) setBackendDetail(null); }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("instances.backend_detail")}</DialogTitle>
          </DialogHeader>
          {backendDetail && (
            <div className="space-y-3 text-[12px]">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">{t("instances.col_product")}</span>
                <span className="font-medium">{backendDetail.data.product_name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">URL</span>
                <code className="font-mono text-[11px]">{backendDetail.data.connection_url}</code>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground w-24 shrink-0">{t("instances.col_status")}</span>
                <Badge className={`text-[10px] ${
                  backendDetail.data.status === "connected" ? "bg-green-100 text-green-700" :
                  backendDetail.data.status === "configured" ? "bg-blue-100 text-blue-700" :
                  "bg-red-100 text-red-700"
                }`}>
                  {backendDetail.data.status}
                </Badge>
              </div>
              {backendDetail.data.openapi_url && (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground w-24 shrink-0">OpenAPI</span>
                  <code className="font-mono text-[11px] truncate">{backendDetail.data.openapi_url}</code>
                  <Badge variant={backendDetail.data.openapi_fetched ? "default" : "destructive"} className="text-[9px]">
                    {backendDetail.data.openapi_fetched ? "fetched" : "pending"}
                  </Badge>
                </div>
              )}
              {backendDetail.data.mcp_config && Object.keys(backendDetail.data.mcp_config).length > 0 && (
                <div>
                  <span className="text-muted-foreground">MCP Config</span>
                  <pre className="mt-1 bg-muted rounded p-2 text-[10px] font-mono overflow-x-auto">
                    {JSON.stringify(backendDetail.data.mcp_config, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </PageShell>
  );
}
