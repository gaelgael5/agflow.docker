import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useServiceTypes } from "@/hooks/useServiceTypes";
import { PromptDialog } from "@/components/PromptDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function ServiceTypesPage() {
  const { t } = useTranslation();
  const { serviceTypes, isLoading, createMutation, deleteMutation } =
    useServiceTypes();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  async function handleAdd(values: Record<string, string>) {
    setAddError(null);
    try {
      await createMutation.mutateAsync({
        name: values.name ?? "",
        display_name: values.display_name ?? "",
      });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setAddError(detail ?? t("service_types.error_generic"));
      throw e;
    }
  }

  async function handleDelete(name: string, display_name: string) {
    if (
      !window.confirm(
        t("service_types.confirm_delete", { name: display_name }),
      )
    )
      return;
    try {
      await deleteMutation.mutateAsync(name);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      window.alert(detail ?? t("service_types.error_generic"));
    }
  }

  return (
    <PageShell maxWidth="5xl">
      <PageHeader
        title={t("service_types.page_title")}
        subtitle={t("service_types.page_subtitle")}
        actions={
          <Button
            onClick={() => {
              setAddError(null);
              setShowAddDialog(true);
            }}
          >
            <Plus className="w-4 h-4" />
            {t("service_types.add_button")}
          </Button>
        }
      />

      <PromptDialog
        open={showAddDialog}
        onOpenChange={setShowAddDialog}
        title={t("service_types.add_dialog_title")}
        description={addError ?? undefined}
        submitLabel={t("common.create")}
        onSubmit={handleAdd}
        fields={[
          {
            name: "display_name",
            label: t("service_types.prompt_display_name"),
          },
          {
            name: "name",
            label: t("service_types.prompt_name"),
            autoSlugFrom: "display_name",
            monospace: true,
          },
        ]}
      />

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
                <TableHead>{t("service_types.col_display_name")}</TableHead>
                <TableHead>{t("service_types.col_name")}</TableHead>
                <TableHead>{t("service_types.col_type")}</TableHead>
                <TableHead className="text-right">
                  {t("service_types.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(serviceTypes ?? []).map((st) => (
                <TableRow key={st.name}>
                  <TableCell className="font-medium">
                    {st.display_name}
                  </TableCell>
                  <TableCell>
                    <code className="text-[12px] text-muted-foreground font-mono">
                      {st.name}
                    </code>
                  </TableCell>
                  <TableCell>
                    {st.is_native ? (
                      <Badge variant="secondary">
                        {t("service_types.native")}
                      </Badge>
                    ) : (
                      <Badge variant="outline">
                        {t("service_types.custom")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {st.is_native ? (
                      <span className="text-muted-foreground text-[12px]">
                        —
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() =>
                          handleDelete(st.name, st.display_name)
                        }
                        aria-label={t("service_types.delete_button")}
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
    </PageShell>
  );
}
