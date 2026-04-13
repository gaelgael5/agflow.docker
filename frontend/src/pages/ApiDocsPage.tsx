import { useTranslation } from "react-i18next";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";

export function ApiDocsPage() {
  const { t } = useTranslation();

  return (
    <PageShell>
      <PageHeader
        title={t("sidebar.api_public")}
        subtitle={t("api_docs.subtitle")}
      />
      <div className="flex-1 min-h-0 -mx-6 -mb-6" style={{ height: "calc(100vh - 160px)" }}>
        <iframe
          src="/docs"
          title="API Documentation"
          className="w-full h-full border-0"
        />
      </div>
    </PageShell>
  );
}
