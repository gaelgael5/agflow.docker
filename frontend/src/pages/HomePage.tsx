import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function HomePage() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div style={{ padding: "2rem" }}>
      <h1>{t("home.welcome")}</h1>
      <nav
        style={{
          marginBottom: "1rem",
          display: "flex",
          flexWrap: "wrap",
          gap: "0.75rem",
          fontSize: "14px",
        }}
      >
        <Link to="/secrets">{t("secrets.page_title")}</Link>
        <span>•</span>
        <Link to="/roles">{t("roles.page_title")}</Link>
        <span>•</span>
        <Link to="/dockerfiles">{t("dockerfiles.page_title")}</Link>
        <span>•</span>
        <Link to="/discovery-services">{t("discovery.page_title")}</Link>
        <span>•</span>
        <Link to="/mcp-catalog">{t("mcp_catalog.page_title")}</Link>
        <span>•</span>
        <Link to="/skills-catalog">{t("skills_catalog.page_title")}</Link>
        <span>•</span>
        <Link to="/agents">{t("agents.page_title")}</Link>
      </nav>
      <button type="button" onClick={handleLogout}>
        {t("home.logout")}
      </button>
    </div>
  );
}
