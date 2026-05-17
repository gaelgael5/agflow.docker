import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { SupervisionKpiCards } from "@/components/supervision/SupervisionKpiCards";
import { SupervisionFilters, type Filters } from "@/components/supervision/SupervisionFilters";
import { SupervisionInstancesTable } from "@/components/supervision/SupervisionInstancesTable";
import { SupervisionInstanceDrawer } from "@/components/supervision/SupervisionInstanceDrawer";
import { SupervisionStreamIndicator } from "@/components/supervision/SupervisionStreamIndicator";
import { useOverview, useInstances } from "@/hooks/useSupervision";
import { useSupervisionStream } from "@/hooks/useSupervisionStream";

export function SupervisionPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const instanceId = searchParams.get("instance");

  const [filters, setFilters] = useState<Filters>({
    status: "all",
    search: "",
    includeDestroyed: false,
  });

  const overview = useOverview();
  const instances = useInstances({
    status: filters.status === "all" ? undefined : filters.status,
    includeDestroyed: filters.includeDestroyed,
  });
  const streamStatus = useSupervisionStream();

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["supervision"] });

  const selectInstance = (id: string) => {
    setSearchParams((prev) => {
      prev.set("instance", id);
      return prev;
    });
  };
  const closeDrawer = () => {
    setSearchParams((prev) => {
      prev.delete("instance");
      return prev;
    });
  };

  return (
    <PageShell>
      <PageHeader
        title={t("supervision.page_title")}
        subtitle={t("supervision.subtitle")}
        actions={
          <div className="flex items-center gap-3">
            <SupervisionStreamIndicator status={streamStatus} />
            <Button
              variant="outline"
              size="sm"
              onClick={refresh}
              aria-label={t("supervision.refresh")}
            >
              <RotateCw className="h-4 w-4 mr-1" /> {t("supervision.refresh")}
            </Button>
          </div>
        }
      />

      <div className="space-y-6">
        <SupervisionKpiCards data={overview.data} />

        <div className="space-y-3">
          <SupervisionFilters value={filters} onChange={setFilters} />

          <SupervisionInstancesTable
            instances={instances.data}
            filters={filters}
            isLoading={instances.isLoading}
            error={instances.error as Error | null}
            onSelect={selectInstance}
            onRetry={() => instances.refetch()}
          />
        </div>
      </div>

      <SupervisionInstanceDrawer instanceId={instanceId} onClose={closeDrawer} />
    </PageShell>
  );
}
