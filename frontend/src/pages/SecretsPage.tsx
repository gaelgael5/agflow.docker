import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { useSecrets } from "@/hooks/useSecrets";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { SecretForm } from "@/components/SecretForm";
import { RevealButton } from "@/components/RevealButton";
import { TestKeyButton } from "@/components/TestKeyButton";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import type { SecretCreate, SecretSummary } from "@/lib/secretsApi";

export function SecretsPage() {
  const { t } = useTranslation();
  const { secrets, isLoading, createMutation, deleteMutation } = useSecrets();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const envStatus = useEnvVarStatuses(
    (secrets ?? []).map((s) => s.var_name),
  );

  async function handleCreate(payload: SecretCreate) {
    setError(null);
    try {
      await createMutation.mutateAsync(payload);
      setShowForm(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      setError(
        status === 409
          ? t("secrets.error_duplicate")
          : t("secrets.error_generic"),
      );
    }
  }

  async function handleDelete(secret: SecretSummary) {
    if (!window.confirm(t("secrets.confirm_delete", { name: secret.var_name })))
      return;
    await deleteMutation.mutateAsync(secret.id);
  }

  return (
    <PageShell>
      <PageHeader
        title={t("secrets.page_title")}
        subtitle={t("secrets.page_subtitle")}
        actions={
          <Button onClick={() => setShowForm(true)} disabled={showForm}>
            <Plus className="w-4 h-4" />
            {t("secrets.add_button")}
          </Button>
        }
      />

      {showForm && (
        <Card className="mb-6">
          <CardContent className="pt-5">
            <SecretForm
              mode="create"
              onSubmit={handleCreate}
              onCancel={() => {
                setShowForm(false);
                setError(null);
              }}
            />
            {error && (
              <p role="alert" className="text-destructive text-[12px] mt-2">
                {error}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-6 w-2/5" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("secrets.col_name")}</TableHead>
                <TableHead>{t("secrets.col_value")}</TableHead>
                <TableHead>{t("secrets.col_scope")}</TableHead>
                <TableHead>{t("secrets.col_used_by")}</TableHead>
                <TableHead className="text-right">
                  {t("secrets.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {secrets?.map((secret) => (
                <TableRow key={secret.id}>
                  <TableCell>
                    <EnvVarStatus
                      name={secret.var_name}
                      status={envStatus.data?.[secret.var_name]}
                    />
                  </TableCell>
                  <TableCell>
                    <RevealButton secretId={secret.id} />
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {secret.scope === "global"
                        ? t("secrets.scope_global")
                        : t("secrets.scope_agent")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-[12px]">
                    {secret.used_by.length === 0
                      ? t("secrets.none_used_by")
                      : secret.used_by.join(", ")}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <TestKeyButton secretId={secret.id} />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(secret)}
                        aria-label={t("secrets.delete")}
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
    </PageShell>
  );
}
