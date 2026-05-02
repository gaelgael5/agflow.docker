import { Grid3x3 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApps } from "@/hooks/useApps";

/**
 * Cross-app launcher menu in the TopBar.
 *
 * The list is read from `apps.json` at the root of the deployment, served by
 * `GET /api/admin/apps`. The file is bind-mounted into the backend container
 * so ops can edit it without rebuilding the image.
 *
 * The button is hidden when no apps are configured (empty list or 4xx).
 */
export function AppsMenu() {
  const { t } = useTranslation();
  const { data, isLoading } = useApps();
  const urls = data?.urls ?? [];

  if (isLoading || urls.length === 0) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors"
          aria-label={t("topbar.apps_menu")}
          title={t("topbar.apps_menu")}
        >
          <Grid3x3 className="w-4 h-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {urls.map((entry) => (
          <DropdownMenuItem key={entry.key} asChild>
            <a
              href={entry.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 cursor-pointer"
            >
              {entry.icon ? (
                <img
                  src={entry.icon}
                  alt=""
                  className="w-4 h-4 shrink-0"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.visibility =
                      "hidden";
                  }}
                />
              ) : (
                <span className="w-4 h-4 shrink-0 rounded bg-muted" />
              )}
              <span className="truncate">{entry.label}</span>
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
