import { useTranslation } from "react-i18next";
import type { ScheduleHistoryEntry } from "@/lib/backupSchedulesApi";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface Props {
  entries: ScheduleHistoryEntry[] | undefined;
  isLoading: boolean;
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function ScheduleHistoryTable({ entries, isLoading }: Props) {
  const { t } = useTranslation();

  if (isLoading) {
    return <p className="text-xs text-muted-foreground p-2">{t("common.loading")}</p>;
  }
  if (!entries || entries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground p-2">
        {t("backups.schedules.historyEmpty")}
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("backups.schedules.historyColDate")}</TableHead>
          <TableHead>{t("backups.schedules.historyColStatus")}</TableHead>
          <TableHead>{t("backups.schedules.historyColSize")}</TableHead>
          <TableHead>{t("backups.schedules.historyColFilename")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((e) => (
          <TableRow key={e.id}>
            <TableCell className="text-xs">
              {new Date(e.created_at).toLocaleString()}
            </TableCell>
            <TableCell>
              <Badge
                variant={
                  e.status === "completed"
                    ? "default"
                    : e.status === "failed"
                      ? "destructive"
                      : "secondary"
                }
              >
                {e.status}
              </Badge>
            </TableCell>
            <TableCell className="text-xs">{formatSize(e.size_bytes)}</TableCell>
            <TableCell className="text-xs font-mono break-all">{e.filename}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
