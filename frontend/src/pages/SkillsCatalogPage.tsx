import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search, Trash2 } from "lucide-react";
import { useDiscoveryServices, useSkillsCatalog } from "@/hooks/useCatalogs";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { SearchModal } from "@/components/SearchModal";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { discoveryApi, type SkillSearchItem } from "@/lib/catalogsApi";

export function SkillsCatalogPage() {
  const { t } = useTranslation();
  const { services } = useDiscoveryServices();
  const { skills, isLoading, installMutation, deleteMutation } =
    useSkillsCatalog();
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

  function handleDelete(id: string, name: string) {
    setDeleteTarget({ id, name });
  }

  async function handleSearch(query: string) {
    if (!selectedServiceId) return [];
    return discoveryApi.searchSkills(selectedServiceId, query);
  }

  async function handleInstall(item: SkillSearchItem) {
    if (!selectedServiceId) return;
    await installMutation.mutateAsync({
      discoveryServiceId: selectedServiceId,
      skillId: item.skill_id,
    });
    setSearchOpen(false);
  }

  const hasServices = (services ?? []).length > 0;

  return (
    <PageShell>
      <PageHeader
        title={t("skills_catalog.page_title")}
        subtitle={t("skills_catalog.page_subtitle")}
        actions={
          hasServices && (
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={selectedServiceId ?? ""}
                onValueChange={(v) => setSelectedServiceId(v || null)}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder={t("skills_catalog.select_service")} />
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
                {t("skills_catalog.search_button")}
              </Button>
            </div>
          )
        }
      />

      {!hasServices && (
        <Card className="p-8 text-center text-muted-foreground text-[13px] italic mb-6">
          {t("skills_catalog.no_services")}
        </Card>
      )}

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (skills ?? []).length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-[13px] italic">
            {t("skills_catalog.no_skills")}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("skills_catalog.col_name")}</TableHead>
                <TableHead>{t("skills_catalog.col_id")}</TableHead>
                <TableHead>{t("skills_catalog.col_description")}</TableHead>
                <TableHead className="text-right">
                  {t("skills_catalog.col_actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {skills?.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>
                    <code className="text-[11px] text-muted-foreground font-mono">
                      {s.skill_id}
                    </code>
                  </TableCell>
                  <TableCell className="text-[12px] text-muted-foreground max-w-md truncate">
                    {s.description}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDelete(s.id, s.name)}
                      aria-label={t("skills_catalog.delete_button")}
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

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title={t("skills_catalog.confirm_delete_title")}
        description={t("skills_catalog.confirm_delete_message", { name: deleteTarget?.name ?? "" })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />

      {searchOpen && selectedServiceId && (
        <SearchModal<SkillSearchItem>
          title={t("skills_catalog.page_title")}
          onSearch={handleSearch}
          onAdd={handleInstall}
          renderItem={(item) => (
            <div>
              <strong className="text-[13px]">{item.name}</strong>{" "}
              <code className="text-[11px] text-muted-foreground font-mono">
                {item.skill_id}
              </code>
              <div className="text-[12px] text-muted-foreground">
                {item.description}
              </div>
            </div>
          )}
          onClose={() => setSearchOpen(false)}
        />
      )}
    </PageShell>
  );
}
