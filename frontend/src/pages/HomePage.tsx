import { useTranslation } from "react-i18next";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";

export function HomePage() {
  const { t } = useTranslation();
  return (
    <PageShell>
      <PageHeader title={t("home.welcome")} subtitle={t("home.subtitle")} />
    </PageShell>
  );
}
