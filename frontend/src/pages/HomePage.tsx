import { useTranslation } from "react-i18next";

export function HomePage() {
  const { t } = useTranslation();
  return (
    <div className="px-8 py-10 max-w-6xl">
      <h1 className="text-[26px] font-semibold text-foreground tracking-tight">
        {t("home.welcome")}
      </h1>
      <p className="text-muted-foreground mt-1.5">
        {t("home.subtitle")}
      </p>
    </div>
  );
}
