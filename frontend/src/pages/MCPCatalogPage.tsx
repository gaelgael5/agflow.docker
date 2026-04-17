import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { ExternalLink, Search, Trash2 } from "lucide-react";
import { useDiscoveryServices, useMCPCatalog } from "@/hooks/useCatalogs";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SearchModal } from "@/components/SearchModal";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { discoveryApi, type MCPSearchItem } from "@/lib/catalogsApi";

export function MCPCatalogPage() {
  const { t } = useTranslation();
  const { services } = useDiscoveryServices();
  const { mcps, isLoading, installMutation, deleteMutation } = useMCPCatalog();
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    if (selectedServiceId === null && services && services.length > 0) {
      setSelectedServiceId(services[0]!.id);
    }
  }, [services, selectedServiceId]);

  const grouped = (mcps ?? []).reduce<Record<string, typeof mcps>>((acc, m) => {
    const key = m.repo || "(other)";
    if (!acc[key]) acc[key] = [];
    acc[key]!.push(m);
    return acc;
  }, {});

  function handleDelete(id: string, name: string) {
    setDeleteTarget({ id, name });
  }

  async function handleSearch(query: string, semantic: boolean) {
    if (!selectedServiceId) return [];
    return discoveryApi.searchMcp(selectedServiceId, query, semantic);
  }

  async function handleInstall(item: MCPSearchItem) {
    if (!selectedServiceId) return;
    await installMutation.mutateAsync({
      discoveryServiceId: selectedServiceId,
      packageId: String(item.package_id),
    });
  }

  const hasServices = (services ?? []).length > 0;

  return (
    <PageShell>
      <PageHeader
        title={t("mcp_catalog.page_title")}
        subtitle={t("mcp_catalog.page_subtitle")}
        actions={
          hasServices && (
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={selectedServiceId ?? ""}
                onValueChange={(v) => setSelectedServiceId(v || null)}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder={t("mcp_catalog.select_service")} />
                </SelectTrigger>
                <SelectContent>
                  {services?.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                onClick={() => setSearchOpen(true)}
                disabled={!selectedServiceId}
              >
                <Search className="w-4 h-4" />
                {t("mcp_catalog.search_button")}
              </Button>
            </div>
          )
        }
      />

      {!hasServices && (
        <Card className="p-8 text-center text-muted-foreground text-[13px] italic mb-6">
          {t("mcp_catalog.no_services")}
        </Card>
      )}

      {isLoading ? (
        <Card>
          <CardContent className="pt-5 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </CardContent>
        </Card>
      ) : (mcps ?? []).length === 0 ? (
        <Card className="p-8 text-center text-muted-foreground text-[13px] italic">
          {t("mcp_catalog.no_mcps")}
        </Card>
      ) : (
        <div className="space-y-5">
          {Object.entries(grouped).map(([repo, list]) => (
            <div key={repo}>
              <div className="flex items-baseline gap-2 mb-2">
                <h3 className="text-[14px] font-semibold text-foreground">
                  {repo}
                </h3>
                <span className="text-[11px] text-muted-foreground">
                  ({list?.length ?? 0})
                </span>
              </div>
              <Card className="overflow-hidden">
                <ul className="divide-y">
                  {list?.map((m) => (
                    <li
                      key={m.id}
                      className="flex items-center gap-3 p-3 hover:bg-secondary/40 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <strong className="text-[13px] text-foreground truncate">
                            {m.name}
                          </strong>
                          <Badge variant="secondary" className="font-mono text-[10px]">
                            {m.transport}
                          </Badge>
                          <code className="text-[11px] text-muted-foreground font-mono hidden sm:inline">
                            {m.package_id}
                          </code>
                        </div>
                        {m.short_description && (
                          <div className="text-[12px] text-muted-foreground mt-0.5 truncate">
                            {m.short_description}
                          </div>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(m.id, m.name)}
                        aria-label={t("mcp_catalog.delete_button")}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("mcp_catalog.confirm_delete_title")}
        description={t("mcp_catalog.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />

      {searchOpen && selectedServiceId && (
        <SearchModal<MCPSearchItem>
          title={t("mcp_catalog.page_title")}
          onSearch={handleSearch}
          onAdd={handleInstall}
          isInstalled={(item) =>
            (mcps ?? []).some(
              (m) => String(m.package_id) === String(item.package_id),
            )
          }
          groupBy={(item) => item.category}
          renderItem={(item) => (
            <MCPSearchResultItem
              item={item}
              serviceId={selectedServiceId}
            />
          )}
          onClose={() => setSearchOpen(false)}
        />
      )}
    </PageShell>
  );
}

function MCPSearchResultItem({
  item,
  serviceId,
}: {
  item: MCPSearchItem;
  serviceId: string;
}) {
  const { t, i18n } = useTranslation();
  const [summary, setSummary] = useState<string | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [expanded, setExpanded] = useState(false);

  async function handleShowSummary() {
    if (summary !== null) {
      setExpanded(!expanded);
      return;
    }
    setLoadingSummary(true);
    const culture = i18n.language.startsWith("fr") ? "fr" : "en";
    const text = await discoveryApi.getSummary(serviceId, String(item.package_id), culture);
    setSummary(text ?? t("mcp_catalog.no_summary"));
    setExpanded(true);
    setLoadingSummary(false);
  }

  return (
    <div
      className={item.has_summaries ? "cursor-pointer" : ""}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a")) return;
        if (item.has_summaries) handleShowSummary();
      }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <strong className="text-[13px]">{item.name}</strong>
        <Badge variant="secondary" className="font-mono text-[10px]">
          {item.transport}
        </Badge>
        {item.category && (
          <Badge variant="outline" className="text-[10px]">
            {item.category}
          </Badge>
        )}
        {item.repo && (
          <span className="text-[11px] text-muted-foreground font-mono">
            {item.repo}
          </span>
        )}
        {item.repo_url && (
          <a
            href={item.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-primary hover:underline flex items-center gap-1"
          >
            <ExternalLink className="w-3 h-3" />
            Repo
          </a>
        )}
        {item.documentation_url && (
          <a
            href={item.documentation_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-primary hover:underline flex items-center gap-1"
          >
            <ExternalLink className="w-3 h-3" />
            Doc
          </a>
        )}
        {loadingSummary && (
          <span className="text-[11px] text-muted-foreground">{t("mcp_catalog.loading_summary")}</span>
        )}
      </div>
      {item.short_description && (
        <div className="text-[12px] text-muted-foreground mt-0.5">
          {item.short_description}
        </div>
      )}
      {expanded && summary && (
        <div className="mt-2 p-3 rounded-md bg-muted text-[12px] max-h-60 overflow-y-auto prose prose-sm dark:prose-invert prose-headings:text-[13px] prose-headings:font-semibold prose-p:my-1 prose-ul:my-1 prose-li:my-0 max-w-none">
          <Markdown>{summary}</Markdown>
        </div>
      )}
    </div>
  );
}
