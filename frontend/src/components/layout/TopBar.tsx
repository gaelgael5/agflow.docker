import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell, ChevronRight, Menu, Search } from "lucide-react";

interface Props {
  onOpenSidebar?: () => void;
}

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

export function TopBar({ onOpenSidebar }: Props) {
  const { t } = useTranslation();
  const location = useLocation();
  const crumb = resolveCrumbs(location.pathname, t);

  return (
    <header className="h-14 border-b bg-card flex items-center justify-between px-4 md:px-6 shrink-0">
      <div className="flex items-center gap-2 text-[13px] min-w-0">
        {onOpenSidebar && (
          <button
            type="button"
            onClick={onOpenSidebar}
            className="md:hidden w-8 h-8 rounded-md hover:bg-secondary flex items-center justify-center text-muted-foreground shrink-0"
            aria-label="Open menu"
          >
            <Menu className="w-4 h-4" />
          </button>
        )}
        {crumb ? (
          <>
            {/* Section label hidden on small screens to save space */}
            <span className="text-muted-foreground hidden sm:inline">
              {crumb.section}
            </span>
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/50 hidden sm:inline" />
            <span className="text-foreground font-medium truncate">
              {crumb.page}
            </span>
          </>
        ) : (
          <span className="text-foreground font-medium truncate">
            {t("home.welcome")}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="hidden sm:flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors"
          aria-label="Search"
        >
          <Search className="w-4 h-4" />
        </button>
        <button
          type="button"
          className="hidden sm:flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors"
          aria-label="Notifications"
        >
          <Bell className="w-4 h-4" />
        </button>
        <div className="hidden sm:block w-px h-5 bg-border mx-1" />
        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-[11px] font-semibold shrink-0">
          GB
        </div>
      </div>
    </header>
  );
}
