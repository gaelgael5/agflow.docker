import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell, ChevronRight, Search } from "lucide-react";

interface Crumb {
  section: string;
  page: string;
}

function resolveCrumbs(path: string, t: (k: string) => string): Crumb | null {
  if (path === "/") return null;
  if (path.startsWith("/secrets"))
    return { section: t("sidebar.section_platform"), page: t("secrets.page_title") };
  if (path.startsWith("/dockerfiles"))
    return {
      section: t("sidebar.section_platform"),
      page: t("dockerfiles.page_title"),
    };
  if (path.startsWith("/roles"))
    return { section: t("sidebar.section_platform"), page: t("roles.page_title") };
  if (path.startsWith("/service-types"))
    return {
      section: t("sidebar.section_platform"),
      page: t("service_types.page_title"),
    };
  if (path.startsWith("/discovery-services"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("discovery.page_title"),
    };
  if (path.startsWith("/mcp-catalog"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("mcp_catalog.page_title"),
    };
  if (path.startsWith("/skills-catalog"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("skills_catalog.page_title"),
    };
  if (path.startsWith("/agents"))
    return {
      section: t("sidebar.section_orchestration"),
      page: t("agents.page_title"),
    };
  return null;
}

export function TopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const crumb = resolveCrumbs(location.pathname, t);

  return (
    <header className="h-14 border-b bg-card flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-2 text-[13px]">
        {crumb ? (
          <>
            <span className="text-muted-foreground">{crumb.section}</span>
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/50" />
            <span className="text-foreground font-medium">{crumb.page}</span>
          </>
        ) : (
          <span className="text-foreground font-medium">{t("home.welcome")}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="w-8 h-8 rounded-md hover:bg-secondary flex items-center justify-center text-muted-foreground transition-colors"
          aria-label="Search"
        >
          <Search className="w-4 h-4" />
        </button>
        <button
          type="button"
          className="w-8 h-8 rounded-md hover:bg-secondary flex items-center justify-center text-muted-foreground transition-colors"
          aria-label="Notifications"
        >
          <Bell className="w-4 h-4" />
        </button>
        <div className="w-px h-5 bg-border mx-1" />
        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-[11px] font-semibold">
          GB
        </div>
      </div>
    </header>
  );
}
