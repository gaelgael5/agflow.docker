import { NavLink, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Bot,
  BookMarked,
  Boxes,
  FileCode2,
  Globe,
  KeyRound,
  LogOut,
  Moon,
  PlugZap,
  RadioTower,
  Tags,
  UserRoundCog,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  disabled?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

export function Sidebar() {
  const { t } = useTranslation();
  const location = useLocation();
  const { logout } = useAuth();

  const sections: NavSection[] = [
    {
      title: t("sidebar.section_platform"),
      items: [
        { to: "/secrets", label: t("secrets.page_title"), icon: KeyRound },
        { to: "/dockerfiles", label: t("dockerfiles.page_title"), icon: FileCode2 },
        { to: "/roles", label: t("roles.page_title"), icon: UserRoundCog },
        { to: "/service-types", label: t("service_types.page_title"), icon: Tags },
      ],
    },
    {
      title: t("sidebar.section_catalogs"),
      items: [
        { to: "/discovery-services", label: t("discovery.page_title"), icon: RadioTower },
        { to: "/mcp-catalog", label: t("mcp_catalog.page_title"), icon: PlugZap },
        { to: "/skills-catalog", label: t("skills_catalog.page_title"), icon: BookMarked },
      ],
    },
    {
      title: t("sidebar.section_orchestration"),
      items: [
        { to: "/agents", label: t("agents.page_title"), icon: Bot },
        { to: "/api", label: t("sidebar.api_public"), icon: Globe, disabled: true },
        { to: "/supervision", label: t("sidebar.supervision"), icon: Activity, disabled: true },
      ],
    },
  ];

  return (
    <aside className="w-60 shrink-0 border-r bg-card flex flex-col">
      {/* Logo */}
      <div className="h-14 border-b flex items-center px-5">
        <NavLink to="/" className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-primary flex items-center justify-center shadow-sm">
            <Boxes className="w-4 h-4 text-primary-foreground" />
          </div>
          <span className="font-semibold text-foreground tracking-tight">agflow</span>
          <span className="text-[11px] text-muted-foreground font-medium ml-0.5">docker</span>
        </NavLink>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-5 space-y-6 overflow-y-auto text-[13px]">
        {sections.map((section) => (
          <div key={section.title}>
            <div className="px-2 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
              {section.title}
            </div>
            {section.items.map((item) => {
              const Icon = item.icon;
              if (item.disabled) {
                return (
                  <div
                    key={item.to}
                    className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-muted-foreground/60 cursor-not-allowed"
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span>{item.label}</span>
                    <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-secondary text-muted-foreground font-medium">
                      soon
                    </span>
                  </div>
                );
              }
              const isActive =
                location.pathname === item.to ||
                location.pathname.startsWith(item.to + "/");
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "flex items-center gap-2.5 px-2 py-1.5 rounded-md transition-colors",
                    isActive
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t p-3 space-y-0.5 text-[13px]">
        <button
          type="button"
          className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground w-full transition-colors"
        >
          <Moon className="w-4 h-4" />
          <span>{t("sidebar.theme_dark")}</span>
        </button>
        <button
          type="button"
          onClick={logout}
          className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground w-full transition-colors"
        >
          <LogOut className="w-4 h-4" />
          <span>{t("home.logout")}</span>
        </button>
      </div>
    </aside>
  );
}
