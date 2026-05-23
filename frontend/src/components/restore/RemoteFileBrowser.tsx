import type { JSX } from "react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Folder, File, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { restoreApi } from "@/lib/restoreApi";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isBackupFile(name: string): boolean {
  return name.endsWith(".sql.gz") || name.endsWith(".dump") || name.endsWith(".sql");
}

interface RemoteFileBrowserProps {
  vaultUrl: string;
  vaultApiKey: string;
  connectionType: "sftp" | "s3" | "ftps" | "gdrive";
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;
  onSelect: (file: { path: string; name: string; size_bytes: number | null }) => void;
}

export function RemoteFileBrowser({
  vaultUrl,
  vaultApiKey,
  connectionType,
  manualFields,
  vaultMappings,
  onSelect,
}: RemoteFileBrowserProps): JSX.Element {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState(manualFields["path"] ?? "/");
  const [breadcrumbs, setBreadcrumbs] = useState<string[]>([manualFields["path"] ?? "/"]);

  const { data: entries = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["restore-browse", connectionType, currentPath, vaultMappings],
    queryFn: () =>
      restoreApi.browse({
        connection_type: connectionType,
        manual_fields: { ...manualFields, path: currentPath },
        vault_mappings: vaultMappings,
        vault: { url: vaultUrl, api_key: vaultApiKey },
        path: currentPath,
      }),
  });

  function navigateTo(path: string) {
    setCurrentPath(path);
    setBreadcrumbs((prev) => [...prev, path]);
  }

  function navigateToBreadcrumb(index: number) {
    const path = breadcrumbs[index];
    if (!path) return;
    setBreadcrumbs((prev) => prev.slice(0, index + 1));
    setCurrentPath(path);
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  if (isError) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-destructive">{t("restore.browse_error")}</p>
        <button className="text-sm text-primary underline" onClick={() => void refetch()}>
          {t("common.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1 text-sm text-muted-foreground flex-wrap">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3" />}
            <button
              className={cn(
                "hover:text-foreground",
                i === breadcrumbs.length - 1 && "text-foreground font-medium",
              )}
              onClick={() => navigateToBreadcrumb(i)}
            >
              {i === 0 ? t("restore.browse_root") : crumb.split("/").at(-1)}
            </button>
          </span>
        ))}
      </div>

      <div className="rounded-md border divide-y">
        {entries.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {t("restore.browse_empty")}
          </p>
        )}
        {entries.map((entry) => (
          <button
            key={entry.path}
            className={cn(
              "flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/50 transition-colors",
              isBackupFile(entry.name) && "hover:bg-primary/5",
            )}
            onClick={() => {
              if (entry.is_dir) {
                navigateTo(entry.path);
              } else if (isBackupFile(entry.name)) {
                onSelect({ path: entry.path, name: entry.name, size_bytes: entry.size_bytes });
              }
            }}
          >
            {entry.is_dir ? (
              <Folder className="h-4 w-4 text-yellow-500 shrink-0" />
            ) : (
              <File
                className={cn(
                  "h-4 w-4 shrink-0",
                  isBackupFile(entry.name) ? "text-primary" : "text-muted-foreground",
                )}
              />
            )}
            <span className={cn("flex-1 text-sm", !entry.is_dir && !isBackupFile(entry.name) && "text-muted-foreground")}>
              {entry.name}
            </span>
            {!entry.is_dir && (
              <span className="text-xs text-muted-foreground">{formatBytes(entry.size_bytes)}</span>
            )}
            {isBackupFile(entry.name) && (
              <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                backup
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
