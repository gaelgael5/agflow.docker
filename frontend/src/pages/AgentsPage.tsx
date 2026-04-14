import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Copy, Download, Pencil, Plus, Search, Trash2, Upload } from "lucide-react";
import { agentsApi } from "@/lib/agentsApi";
import { useAgents } from "@/hooks/useAgents";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PromptDialog } from "@/components/PromptDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

export function AgentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, isLoading, deleteMutation, duplicateMutation } = useAgents();
  const [filter, setFilter] = useState("");
  const [duplicateTargetId, setDuplicateTargetId] = useState<string | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  function handleDelete(id: string, name: string) {
    setDeleteTarget({ id, name });
  }

  async function handleDuplicateSubmit(values: Record<string, string>) {
    if (!duplicateTargetId) return;
    await duplicateMutation.mutateAsync({
      id: duplicateTargetId,
      slug: values.slug ?? "",
      displayName: values.displayName ?? "",
    });
  }

  const filtered = (agents ?? []).filter((a) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return (
      a.slug.toLowerCase().includes(q) ||
      a.display_name.toLowerCase().includes(q) ||
      a.dockerfile_id.toLowerCase().includes(q) ||
      a.role_id.toLowerCase().includes(q)
    );
  });

  return (
    <PageShell>
      <PageHeader
        title={t("agents.page_title")}
        subtitle={t("agents.page_subtitle")}
        actions={
          <div className="flex items-center gap-0.5 rounded-md border bg-background p-0.5">
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={() => navigate("/agents/new")}
              title={t("agents.add_button")}
            >
              <Plus className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={() => importInputRef.current?.click()}
              title={t("common.import")}
            >
              <Upload className="w-3.5 h-3.5" />
            </Button>
            <input
              ref={importInputRef}
              type="file"
              accept=".zip"
              className="hidden"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                e.target.value = "";
                try {
                  const agent = await agentsApi.importZip(f);
                  navigate(`/agents/${agent.id}`);
                } catch {
                  // error handled by axios interceptor
                }
              }}
            />
          </div>
        }
      />

      <div className="mb-4 relative max-w-sm">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder={t("agents.filter_placeholder")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="pl-9"
        />
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-6 w-2/5" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-[13px]">
            {t("agents.no_agents")}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("agents.col_slug")}</TableHead>
                <TableHead>{t("agents.col_name")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("agents.col_dockerfile")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("agents.col_role")}</TableHead>
                <TableHead>{t("agents.col_status")}</TableHead>
                <TableHead className="text-right">
                  {t("agents.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((a) => (
                <TableRow
                  key={a.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/agents/${a.id}`)}
                >
                  <TableCell>
                    <code className="text-[12px] text-muted-foreground font-mono">
                      {a.slug}
                    </code>
                  </TableCell>
                  <TableCell className="font-medium">{a.display_name}</TableCell>
                  <TableCell className="hidden md:table-cell">
                    <code className="text-[12px] text-muted-foreground font-mono">
                      {a.dockerfile_id}
                    </code>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <code className="text-[12px] text-muted-foreground font-mono">
                      {a.role_id}
                    </code>
                  </TableCell>
                  <TableCell>
                    {a.has_errors ? (
                      <Badge variant="destructive">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                        {t("agents.error_badge")}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground text-[12px]">—</span>
                    )}
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => navigate(`/agents/${a.id}`)}
                        title={t("agents.edit_button")}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDuplicateTargetId(a.id)}
                        title={t("agents.duplicate_button")}
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={async () => {
                          const blob = await agentsApi.exportZip(a.id);
                          const url = URL.createObjectURL(blob);
                          const link = document.createElement("a");
                          link.href = url;
                          link.download = `${a.slug}.zip`;
                          link.click();
                          URL.revokeObjectURL(url);
                        }}
                        title={t("common.export")}
                      >
                        <Download className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(a.id, a.display_name)}
                        title={t("agents.delete_button")}
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

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("agents.confirm_delete_title")}
        description={t("agents.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />

      <PromptDialog
        open={duplicateTargetId !== null}
        onOpenChange={(open) => !open && setDuplicateTargetId(null)}
        title={t("agents.duplicate_dialog_title")}
        submitLabel={t("common.duplicate")}
        onSubmit={handleDuplicateSubmit}
        fields={[
          { name: "displayName", label: t("agents.duplicate_prompt_name") },
          {
            name: "slug",
            label: t("agents.duplicate_prompt_slug"),
            autoSlugFrom: "displayName",
            slugSeparator: "-",
            monospace: true,
          },
        ]}
      />
    </PageShell>
  );
}
