import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { useImageRegistries } from "@/hooks/useImageRegistries";
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
import type { RegistrySummary } from "@/lib/imageRegistriesApi";

export function ImageRegistriesPage() {
  const { t } = useTranslation();
  const { registries, isLoading, createMutation, deleteMutation } = useImageRegistries();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  return (
    <PageShell>
      <PageHeader
        title={t("registries.page_title")}
        subtitle={t("registries.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("registries.add_button")}
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
                <TableHead>{t("registries.col_id")}</TableHead>
                <TableHead>{t("registries.col_name")}</TableHead>
                <TableHead>{t("registries.col_url")}</TableHead>
                <TableHead>{t("registries.col_auth")}</TableHead>
                <TableHead className="text-right">{t("registries.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(registries ?? []).map((r: RegistrySummary) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <code className="text-[12px]">{r.id}</code>
                    {r.is_default && (
                      <Badge variant="secondary" className="ml-2 text-[10px]">
                        {t("registries.default_badge")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{r.display_name}</TableCell>
                  <TableCell className="font-mono text-[12px] text-muted-foreground">{r.url}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px]">{r.auth_type}</Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {!r.is_default && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget({ id: r.id, name: r.display_name })}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    )}
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
        title={t("registries.dialog_title")}
        fields={[
          { name: "display_name", label: t("registries.field_name"), required: true },
          { name: "id", label: t("registries.field_id"), required: true, autoSlugFrom: "display_name", slugSeparator: "-", monospace: true },
          { name: "url", label: t("registries.field_url"), required: true, monospace: true },
        ]}
        onSubmit={async (values) => {
          await createMutation.mutateAsync({
            id: values.id ?? "",
            display_name: values.display_name ?? "",
            url: values.url ?? "",
          });
          setShowCreate(false);
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("registries.confirm_delete_title")}
        description={t("registries.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />
    </PageShell>
  );
}
