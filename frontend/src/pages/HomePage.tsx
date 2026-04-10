import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
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
      <button type="button" onClick={handleLogout}>
        {t("home.logout")}
      </button>
    </div>
  );
}
