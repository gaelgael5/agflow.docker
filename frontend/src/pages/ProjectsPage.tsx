import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { useProjects } from "@/hooks/useProjects";
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

const ENV_COLORS: Record<string, string> = {
  dev: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  staging: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  prod: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
};

export function ProjectsPage() {
  const { t } = useTranslation();
  const { projects, isLoading, createMutation, deleteMutation } = useProjects();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  return (
    <PageShell>
      <PageHeader
        title={t("projects.page_title")}
        subtitle={t("projects.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("projects.add_button")}
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (projects ?? []).length === 0 ? (
          <p className="text-muted-foreground italic p-6">{t("projects.no_projects")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("projects.col_id")}</TableHead>
                <TableHead>{t("projects.col_name")}</TableHead>
                <TableHead>{t("projects.col_env")}</TableHead>
                <TableHead className="text-right">{t("projects.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(projects ?? []).map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <code className="text-[12px]">{p.id}</code>
                  </TableCell>
                  <TableCell>
                    <div>
                      <span className="font-medium">{p.display_name}</span>
                      {p.description && (
                        <p className="text-[11px] text-muted-foreground mt-0.5">{p.description}</p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge className={`text-[10px] ${ENV_COLORS[p.environment] ?? ""}`}>
                      {p.environment}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleteTarget({ id: p.id, name: p.display_name })}
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

      <PromptDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        title={t("projects.dialog_title")}
        fields={[
          { name: "display_name", label: t("projects.field_name"), required: true },
          { name: "id", label: t("projects.field_id"), required: true, autoSlugFrom: "display_name", slugSeparator: "-", monospace: true },
          { name: "description", label: t("projects.field_description") },
          { name: "environment", label: t("projects.field_environment"), defaultValue: "dev" },
        ]}
        onSubmit={async (values) => {
          await createMutation.mutateAsync({
            id: values.id ?? "",
            display_name: values.display_name ?? "",
            description: values.description ?? "",
            environment: (values.environment as "dev" | "staging" | "prod") ?? "dev",
          });
          setShowCreate(false);
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("projects.confirm_delete_title")}
        description={t("projects.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />
    </PageShell>
  );
}
