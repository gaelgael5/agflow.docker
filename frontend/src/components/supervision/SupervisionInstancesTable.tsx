import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { SupervisedInstance } from "@/lib/supervisionApi";
import type { Filters } from "./SupervisionFilters";

interface Props {
  instances: SupervisedInstance[] | undefined;
  filters: Filters;
  isLoading: boolean;
  error: Error | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "busy"
      ? "bg-primary/15 text-primary"
      : status === "idle"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
      : status === "error"
      ? "bg-destructive/15 text-destructive"
      : "bg-muted text-muted-foreground"; // destroyed / unknown
  return (
    <Badge variant="outline" className={cn("font-mono uppercase tracking-wide", tone)}>
      <span className="mr-1.5 w-1.5 h-1.5 rounded-full bg-current" aria-hidden />
      {status}
    </Badge>
  );
}

export function SupervisionInstancesTable({
  instances,
  filters,
  isLoading,
  error,
  onSelect,
  onRetry,
}: Props) {
  const { t, i18n } = useTranslation();

  const rtf = useMemo(
    () => new Intl.RelativeTimeFormat(i18n.language, { numeric: "auto" }),
    [i18n.language],
  );

  const formatRelative = (iso: string): string => {
    const diffMs = new Date(iso).getTime() - Date.now();
    const diffSec = Math.round(diffMs / 1000);
    if (Math.abs(diffSec) < 60) return rtf.format(diffSec, "second");
    const diffMin = Math.round(diffSec / 60);
    if (Math.abs(diffMin) < 60) return rtf.format(diffMin, "minute");
    const diffH = Math.round(diffMin / 60);
    if (Math.abs(diffH) < 24) return rtf.format(diffH, "hour");
    const diffD = Math.round(diffH / 24);
    return rtf.format(diffD, "day");
  };

  const filtered = useMemo(() => {
    if (!instances) return [];
    const q = filters.search.trim().toLowerCase();
    const list = q
      ? instances.filter(
          (i) =>
            (i.mission?.toLowerCase().includes(q) ?? false) ||
            i.agent_id.toLowerCase().includes(q) ||
            i.session_id.toLowerCase().includes(q),
        )
      : instances;
    return [...list].sort((a, b) =>
      a.last_activity_at < b.last_activity_at ? 1 : -1,
    );
  }, [instances, filters.search]);

  if (error) {
    return (
      <div
        role="alert"
        className="rounded-md border border-destructive/30 bg-destructive/5 p-4 flex items-center justify-between"
      >
        <span className="text-sm text-destructive">
          {t("supervision.table.error")} : {error.message}
        </span>
        <Button size="sm" variant="outline" onClick={onRetry}>
          {t("supervision.table.retry")}
        </Button>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[110px]">{t("supervision.table.col.status")}</TableHead>
          <TableHead>{t("supervision.table.col.mission")}</TableHead>
          <TableHead>{t("supervision.table.col.agent")}</TableHead>
          <TableHead>{t("supervision.table.col.session")}</TableHead>
          <TableHead className="w-[140px]">{t("supervision.table.col.last_activity")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading
          ? [0, 1, 2, 3, 4].map((i) => (
              <TableRow key={`sk-${i}`} data-skeleton-row>
                <TableCell colSpan={5}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ))
          : filtered.length === 0
          ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-sm text-muted-foreground py-8">
                  {t("supervision.table.empty")}
                </TableCell>
              </TableRow>
            )
          : filtered.map((row) => (
              <TableRow
                key={row.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(row.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(row.id);
                  }
                }}
                className={cn(
                  "cursor-pointer hover:bg-muted/50",
                  row.destroyed_at && "opacity-60",
                )}
              >
                <TableCell><StatusBadge status={row.destroyed_at ? "destroyed" : row.status} /></TableCell>
                <TableCell className={cn(!row.mission && "text-muted-foreground")}>
                  {row.mission ?? t("supervision.table.no_mission")}
                </TableCell>
                <TableCell className="font-mono text-xs">{row.agent_id}</TableCell>
                <TableCell className="font-mono text-xs">{row.session_id.slice(0, 8)}…</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatRelative(row.last_activity_at)}
                </TableCell>
              </TableRow>
            ))}
      </TableBody>
    </Table>
  );
}
