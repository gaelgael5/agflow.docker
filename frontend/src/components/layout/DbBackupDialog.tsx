import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Download, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function extractFilename(cd: string | undefined, fallback: string): string {
  if (!cd) return fallback;
  const m = /filename="([^"]+)"/.exec(cd);
  return m?.[1] ?? fallback;
}

/**
 * Dialog d'export / import de la base Postgres.
 *
 * Export : GET /api/admin/system/db/export → téléchargement direct du
 * pg_dump gzippé (le browser sauve le fichier avec son timestamp).
 *
 * Import : POST /api/admin/system/db/import (multipart) — DESTRUCTIF, le
 * dump utilise --clean --if-exists côté pg_dump donc toutes les tables
 * existantes sont DROP avant recréation. Le bouton est isolé et exige
 * une 2e confirmation explicite avant l'envoi.
 */
export function DbBackupDialog({ open, onOpenChange }: Props) {
  const { t } = useTranslation();
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const r = await api.get("/admin/system/db/export", {
        responseType: "blob",
      });
      const filename = extractFilename(
        r.headers["content-disposition"] as string | undefined,
        "agflow-db.sql.gz",
      );
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(t("db_backup.export_success", { filename }));
    } catch {
      toast.error(t("db_backup.export_error"));
    } finally {
      setExporting(false);
    }
  };

  const handlePickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    e.target.value = "";
    if (f) setPendingFile(f);
  };

  const handleConfirmImport = async () => {
    if (!pendingFile || importing) return;
    setImporting(true);
    try {
      const fd = new FormData();
      fd.append("file", pendingFile);
      await api.post("/admin/system/db/import", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        // Restore peut prendre du temps sur une grosse base
        timeout: 5 * 60 * 1000,
      });
      toast.success(t("db_backup.import_success"));
      setPendingFile(null);
      onOpenChange(false);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? String(err);
      toast.error(t("db_backup.import_error", { detail }));
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("db_backup.title")}</DialogTitle>
          <DialogDescription>{t("db_backup.subtitle")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Export */}
          <div className="rounded border p-3 space-y-2">
            <h3 className="text-[13px] font-semibold flex items-center gap-2">
              <Download className="w-4 h-4" />
              {t("db_backup.export_title")}
            </h3>
            <p className="text-[12px] text-muted-foreground">
              {t("db_backup.export_desc")}
            </p>
            <Button
              type="button"
              size="sm"
              onClick={handleExport}
              disabled={exporting}
              className="w-full"
            >
              {exporting ? (
                <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5 mr-2" />
              )}
              {t("db_backup.export_button")}
            </Button>
          </div>

          {/* Import */}
          <div className="rounded border border-destructive/40 p-3 space-y-2">
            <h3 className="text-[13px] font-semibold flex items-center gap-2 text-destructive">
              <AlertTriangle className="w-4 h-4" />
              {t("db_backup.import_title")}
            </h3>
            <p className="text-[12px] text-muted-foreground">
              {t("db_backup.import_desc")}
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".gz,.sql.gz,application/gzip"
              className="hidden"
              onChange={handlePickFile}
            />
            {pendingFile ? (
              <div className="space-y-2">
                <div className="text-[12px] font-mono bg-muted/40 rounded px-2 py-1 truncate">
                  {pendingFile.name} ({Math.round(pendingFile.size / 1024)} KB)
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={handleConfirmImport}
                    disabled={importing}
                    className="flex-1"
                  >
                    {importing ? (
                      <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
                    ) : (
                      <Upload className="w-3.5 h-3.5 mr-2" />
                    )}
                    {t("db_backup.import_confirm")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setPendingFile(null)}
                    disabled={importing}
                  >
                    {t("db_backup.cancel")}
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                className="w-full"
              >
                <Upload className="w-3.5 h-3.5 mr-2" />
                {t("db_backup.import_pick_file")}
              </Button>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={exporting || importing}
          >
            {t("db_backup.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
