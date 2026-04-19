import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Star, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAiProviders } from "@/hooks/useAiProviders";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { aiProvidersApi } from "@/lib/aiProvidersApi";
import { PromptDialog } from "@/components/PromptDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

const SERVICE_LABELS: Record<string, string> = {
  image_generation: "Génération d'images",
  embedding: "Embedding",
  llm: "LLM",
};

export function AiProvidersPage() {
  const { t } = useTranslation();
  const { providers, isLoading, createMutation, deleteMutation } = useAiProviders();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ serviceType: string; providerName: string; displayName: string } | null>(null);

  const secretNames = useMemo(
    () => (providers ?? []).map((p) => p.secret_ref).filter((r) => r.length > 0),
    [providers],
  );
  const secretStatuses = useEnvVarStatuses(secretNames);

  return (
    <PageShell>
      <PageHeader
        title={t("ai_providers.page_title")}
        subtitle={t("ai_providers.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("ai_providers.add_button")}
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("ai_providers.col_service")}</TableHead>
                <TableHead>{t("ai_providers.col_provider")}</TableHead>
                <TableHead>{t("ai_providers.col_secret")}</TableHead>
                <TableHead>{t("ai_providers.col_status")}</TableHead>
                <TableHead className="text-right">{t("ai_providers.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(providers ?? []).map((p) => (
                <TableRow key={`${p.service_type}-${p.provider_name}`}>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px]">
                      {SERVICE_LABELS[p.service_type] ?? p.service_type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{p.display_name}</span>
                      <code className="text-[11px] text-muted-foreground">{p.provider_name}</code>
                      {p.is_default && (
                        <Star className="w-3 h-3 text-amber-500 fill-amber-500" />
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {p.secret_ref ? (
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`inline-block w-2 h-2 rounded-full shrink-0 ${
                            !secretStatuses.data?.[p.secret_ref]
                              ? "bg-gray-400"
                              : secretStatuses.data[p.secret_ref] === "ok"
                                ? "bg-green-500"
                                : secretStatuses.data[p.secret_ref] === "empty"
                                  ? "bg-orange-500"
                                  : "bg-red-500"
                          }`}
                        />
                        <code className="text-[11px] font-mono">{p.secret_ref}</code>
                      </div>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge className={`text-[10px] ${p.enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {p.enabled ? t("ai_providers.enabled") : t("ai_providers.disabled")}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {!p.is_default && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-[11px]"
                          onClick={async () => {
                            await aiProvidersApi.update(p.service_type, p.provider_name, { is_default: true });
                            toast.success("Défaut mis à jour");
                            // Trigger refetch
                            window.location.reload();
                          }}
                        >
                          <Star className="w-3 h-3" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget({ serviceType: p.service_type, providerName: p.provider_name, displayName: p.display_name })}
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

      <PromptDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        title={t("ai_providers.dialog_title")}
        fields={[
          { name: "service_type", label: t("ai_providers.field_service"), required: true, defaultValue: "image_generation", options: [
            { value: "image_generation", label: "Génération d'images" },
            { value: "embedding", label: "Embedding" },
            { value: "llm", label: "LLM" },
          ]},
          { name: "provider_name", label: t("ai_providers.field_provider"), required: true },
          { name: "display_name", label: t("ai_providers.field_name"), required: true },
          { name: "secret_ref", label: t("ai_providers.field_secret"), monospace: true },
        ]}
        onSubmit={async (values) => {
          await createMutation.mutateAsync({
            service_type: (values.service_type as "image_generation" | "embedding" | "llm") ?? "image_generation",
            provider_name: values.provider_name ?? "",
            display_name: values.display_name ?? "",
            secret_ref: values.secret_ref ?? "",
            is_default: (providers ?? []).filter((p) => p.service_type === values.service_type).length === 0,
          });
          setShowCreate(false);
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("ai_providers.confirm_delete_title")}
        description={t("ai_providers.confirm_delete_message", { name: deleteTarget?.displayName ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) {
            await deleteMutation.mutateAsync({ serviceType: deleteTarget.serviceType, providerName: deleteTarget.providerName });
          }
        }}
      />
    </PageShell>
  );
}
