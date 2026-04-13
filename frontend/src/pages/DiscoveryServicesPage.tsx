import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CircleCheck, CircleX, Plus, Play, Trash2 } from "lucide-react";
import { useDiscoveryServices } from "@/hooks/useCatalogs";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import { PromptDialog } from "@/components/PromptDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { discoveryApi, type ProbeResult } from "@/lib/catalogsApi";

export function DiscoveryServicesPage() {
  const { t } = useTranslation();
  const { services, isLoading, createMutation, deleteMutation } =
    useDiscoveryServices();
  const [testResults, setTestResults] = useState<Record<string, ProbeResult>>(
    {},
  );
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const apiKeyVars = (services ?? [])
    .map((s) => s.api_key_var)
    .filter((v): v is string => Boolean(v));
  const envStatus = useEnvVarStatuses(apiKeyVars);

  async function handleAdd(values: Record<string, string>) {
    await createMutation.mutateAsync({
      id: values.id ?? "",
      name: values.name ?? "",
      base_url: values.base_url ?? "",
      api_key_var: values.api_key_var ? values.api_key_var : null,
    });
  }

  async function handleTest(id: string) {
    const result = await discoveryApi.test(id);
    setTestResults((prev) => ({ ...prev, [id]: result }));
  }

  function handleDelete(id: string, name: string) {
    setDeleteTarget({ id, name });
  }

  return (
    <PageShell>
      <PageHeader
        title={t("discovery.page_title")}
        subtitle={t("discovery.page_subtitle")}
        actions={
          <Button onClick={() => setShowAddDialog(true)}>
            <Plus className="w-4 h-4" />
            {t("discovery.add_button")}
          </Button>
        }
      />

      <PromptDialog
        open={showAddDialog}
        onOpenChange={setShowAddDialog}
        title={t("discovery.add_dialog_title")}
        submitLabel={t("common.create")}
        onSubmit={handleAdd}
        fields={[
          { name: "name", label: t("discovery.prompt_name") },
          {
            name: "id",
            label: t("discovery.prompt_id"),
            autoSlugFrom: "name",
            monospace: true,
          },
          { name: "base_url", label: t("discovery.prompt_base_url") },
          {
            name: "api_key_var",
            label: t("discovery.prompt_api_key_var"),
            required: false,
            monospace: true,
          },
        ]}
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (services ?? []).length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-[13px] italic">
            {t("discovery.no_services")}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("discovery.col_id")}</TableHead>
                <TableHead>{t("discovery.col_name")}</TableHead>
                <TableHead>{t("discovery.col_base_url")}</TableHead>
                <TableHead>{t("discovery.col_api_key")}</TableHead>
                <TableHead className="text-right">
                  {t("discovery.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {services?.map((s) => {
                const test = testResults[s.id];
                return (
                  <TableRow key={s.id}>
                    <TableCell>
                      <code className="text-[12px] text-muted-foreground font-mono">
                        {s.id}
                      </code>
                    </TableCell>
                    <TableCell className="font-medium">{s.name}</TableCell>
                    <TableCell>
                      <code className="text-[11px] text-muted-foreground font-mono">
                        {s.base_url}
                      </code>
                    </TableCell>
                    <TableCell>
                      {s.api_key_var ? (
                        <EnvVarStatus
                          name={s.api_key_var}
                          status={envStatus.data?.[s.api_key_var]}
                        />
                      ) : (
                        <span className="text-muted-foreground text-[12px]">
                          —
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {test && (
                          <span
                            className={
                              test.ok
                                ? "text-emerald-600 text-[11px] mr-1 flex items-center gap-1"
                                : "text-destructive text-[11px] mr-1 flex items-center gap-1"
                            }
                            title={test.detail}
                          >
                            {test.ok ? (
                              <>
                                <CircleCheck className="w-3 h-3" />
                                {t("discovery.test_ok")}
                              </>
                            ) : (
                              <>
                                <CircleX className="w-3 h-3" />
                                {t("discovery.test_ko")}
                              </>
                            )}
                          </span>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleTest(s.id)}
                          aria-label={t("discovery.test_button")}
                        >
                          <Play className="w-3.5 h-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDelete(s.id, s.name)}
                          aria-label={t("discovery.delete_button")}
                        >
                          <Trash2 className="w-3.5 h-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("discovery.confirm_delete_title")}
        description={t("discovery.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) {
            await deleteMutation.mutateAsync(deleteTarget.id);
            setTestResults((prev) => {
              const n = { ...prev };
              delete n[deleteTarget.id];
              return n;
            });
          }
        }}
      />
    </PageShell>
  );
}
