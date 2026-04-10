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
      <nav style={{ marginBottom: "1rem" }}>
        <Link to="/secrets">{t("secrets.page_title")}</Link>
        {" • "}
        <Link to="/roles">{t("roles.page_title")}</Link>
        {" • "}
        <Link to="/dockerfiles">{t("dockerfiles.page_title")}</Link>
      </nav>
      <button type="button" onClick={handleLogout}>
        {t("home.logout")}
      </button>
    </div>
  );
}
