import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FolderKanban, Pencil, Plus, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { projectsApi, type ProjectCreatePayload, type ProjectSummary } from "@/lib/projectsApi";
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
  const navigate = useNavigate();
  const qc = useQueryClient();
  const listQuery = useQuery({ queryKey: ["projects"], queryFn: () => projectsApi.list() });
  const createMutation = useMutation({
    mutationFn: (p: ProjectCreatePayload) => projectsApi.create(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<ProjectCreatePayload> }) =>
      projectsApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<ProjectSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const projects = listQuery.data ?? [];

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
        {listQuery.isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : projects.length === 0 ? (
          <p className="text-muted-foreground italic p-6">{t("projects.no_projects")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("projects.col_name")}</TableHead>
                <TableHead>{t("projects.col_env")}</TableHead>
                <TableHead>{t("projects.col_groups")}</TableHead>
                <TableHead className="text-right">{t("projects.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {projects.map((p) => (
                <TableRow
                  key={p.id}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => navigate(`/projects/${p.id}`)}
                >
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <FolderKanban className="w-4 h-4 text-muted-foreground" />
                      <div>
                        <span className="font-medium">{p.display_name}</span>
                        {p.description && (
                          <p className="text-[11px] text-muted-foreground mt-0.5">{p.description}</p>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge className={`text-[10px] ${ENV_COLORS[p.environment] ?? ""}`}>
                      {p.environment}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px]">
                      {p.group_count} {t("projects.groups")}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => { e.stopPropagation(); setEditTarget(p); }}
                        title={t("common.edit")}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget({ id: p.id, name: p.display_name }); }}
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
        title={t("projects.dialog_title")}
        fields={[
          { name: "display_name", label: t("projects.field_name"), required: true },
          { name: "description", label: t("projects.field_description") },
          {
            name: "environment", label: t("projects.field_environment"), defaultValue: "dev",
            options: [
              { value: "dev", label: "Dev" },
              { value: "staging", label: "Staging" },
              { value: "prod", label: "Prod" },
            ],
          },
          { name: "network", label: t("projects.field_network"), defaultValue: "agflow", monospace: true },
        ]}
        onSubmit={async (values) => {
          await createMutation.mutateAsync({
            display_name: values.display_name ?? "",
            description: values.description ?? "",
            environment: (values.environment as "dev" | "staging" | "prod") ?? "dev",
            network: (values.network ?? "agflow").trim() || "agflow",
          });
          setShowCreate(false);
        }}
      />

      <PromptDialog
        open={editTarget !== null}
        onOpenChange={(o) => { if (!o) setEditTarget(null); }}
        title={t("projects.dialog_edit_title")}
        fields={editTarget ? [
          { name: "display_name", label: t("projects.field_name"), required: true, defaultValue: editTarget.display_name },
          { name: "description", label: t("projects.field_description"), defaultValue: editTarget.description },
          {
            name: "environment", label: t("projects.field_environment"), defaultValue: editTarget.environment,
            options: [
              { value: "dev", label: "Dev" },
              { value: "staging", label: "Staging" },
              { value: "prod", label: "Prod" },
            ],
          },
          { name: "network", label: t("projects.field_network"), defaultValue: editTarget.network || "agflow", monospace: true },
        ] : []}
        onSubmit={async (values) => {
          if (!editTarget) return;
          await updateMutation.mutateAsync({
            id: editTarget.id,
            payload: {
              display_name: values.display_name ?? editTarget.display_name,
              description: values.description ?? "",
              environment: (values.environment as "dev" | "staging" | "prod") ?? editTarget.environment,
              network: (values.network ?? "agflow").trim() || "agflow",
            },
          });
          setEditTarget(null);
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
