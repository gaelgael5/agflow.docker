import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";
import { usePreviewImport, useRunImport } from "@/hooks/useGitSync";
import { type GitSyncImportPreview } from "@/lib/gitSyncApi";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
};

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

export function GitSyncPreviewDialog({ open, onOpenChange }: Props) {
  const { t } = useTranslation();
  const preview = usePreviewImport();
  const runImport = useRunImport();
  const [data, setData] = useState<GitSyncImportPreview | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setData(null);
    preview
      .mutateAsync()
      .then(setData)
      .catch((e) => {
        toast.error(extractErrorMessage(e));
        onOpenChange(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const totals = data?.tables.reduce(
    (acc, row) => ({
      ins: acc.ins + row.to_insert,
      upd: acc.upd + row.to_update,
      del: acc.del + row.to_delete,
    }),
    { ins: 0, upd: 0, del: 0 },
  );

  const handleConfirm = async () => {
    try {
      const r = await runImport.mutateAsync();
      toast.success(
        t("settings.gitSync.toast.importSuccess", {
          ins: r.rows_inserted,
          upd: r.rows_updated,
          del: r.rows_deleted,
        }),
      );
      onOpenChange(false);
    } catch (e) {
      toast.error(
        t("settings.gitSync.toast.importFailed", {
          error: extractErrorMessage(e),
        }),
      );
    }
  };

  const hasRows = !!data && data.tables.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("settings.gitSync.preview.title")}</DialogTitle>
        </DialogHeader>

        {preview.isPending && (
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.preview.loading")}
          </p>
        )}

        {data && data.tables.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.preview.empty")}
          </p>
        )}

        {hasRows && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("settings.gitSync.preview.table")}</TableHead>
                  <TableHead className="text-right">
                    {t("settings.gitSync.preview.toInsert")}
                  </TableHead>
                  <TableHead className="text-right">
                    {t("settings.gitSync.preview.toUpdate")}
                  </TableHead>
                  <TableHead className="text-right">
                    {t("settings.gitSync.preview.toDelete")}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data!.tables.map((row) => (
                  <TableRow key={row.table}>
                    <TableCell className="font-mono text-xs">
                      {row.table}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.to_insert}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.to_update}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.to_delete}
                    </TableCell>
                  </TableRow>
                ))}
                {totals && (
                  <TableRow className="font-semibold border-t-2">
                    <TableCell>{t("settings.gitSync.preview.total")}</TableCell>
                    <TableCell className="text-right">{totals.ins}</TableCell>
                    <TableCell className="text-right">{totals.upd}</TableCell>
                    <TableCell className="text-right">{totals.del}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            <p className="text-sm text-destructive mt-2">
              {t("settings.gitSync.actions.importWarning")}
            </p>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("settings.gitSync.preview.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={!hasRows || runImport.isPending}
          >
            {t("settings.gitSync.preview.confirmImport")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
