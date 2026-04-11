import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDiscoveryServices } from "@/hooks/useCatalogs";
import { useEnvVarStatuses } from "@/hooks/useEnvVarStatus";
import { EnvVarStatus } from "@/components/EnvVarStatus";
import { discoveryApi, type ProbeResult } from "@/lib/catalogsApi";

export function DiscoveryServicesPage() {
  const { t } = useTranslation();
  const { services, isLoading, createMutation, deleteMutation } =
    useDiscoveryServices();
  const [testResults, setTestResults] = useState<Record<string, ProbeResult>>(
    {},
  );

  const apiKeyVars = (services ?? [])
    .map((s) => s.api_key_var)
    .filter((v): v is string => Boolean(v));
  const envStatus = useEnvVarStatuses(apiKeyVars);

  async function handleAdd() {
    const id = window.prompt(t("discovery.prompt_id"));
    if (!id) return;
    const name = window.prompt(t("discovery.prompt_name")) ?? id;
    const base_url = window.prompt(t("discovery.prompt_base_url")) ?? "";
    if (!base_url) return;
    const api_key_var =
      window.prompt(t("discovery.prompt_api_key_var")) || null;
    await createMutation.mutateAsync({ id, name, base_url, api_key_var });
  }

  async function handleTest(id: string) {
    const result = await discoveryApi.test(id);
    setTestResults((prev) => ({ ...prev, [id]: result }));
  }

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(t("discovery.confirm_delete", { name }))) return;
    await deleteMutation.mutateAsync(id);
    setTestResults((prev) => {
      const n = { ...prev };
      delete n[id];
      return n;
    });
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ padding: "2rem", maxWidth: 1200 }}>
      <h1>{t("discovery.page_title")}</h1>
      <p>{t("discovery.page_subtitle")}</p>

      <button
        type="button"
        onClick={handleAdd}
        style={{ marginBottom: "1rem" }}
      >
        {t("discovery.add_button")}
      </button>

      {(services ?? []).length === 0 ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("discovery.no_services")}
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th>{t("discovery.col_id")}</th>
              <th>{t("discovery.col_name")}</th>
              <th>{t("discovery.col_base_url")}</th>
              <th>{t("discovery.col_api_key")}</th>
              <th>{t("discovery.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {services?.map((s) => {
              const test = testResults[s.id];
              return (
                <tr
                  key={s.id}
                  style={{ borderBottom: "1px solid #eee" }}
                >
                  <td>
                    <code>{s.id}</code>
                  </td>
                  <td>{s.name}</td>
                  <td>
                    <code style={{ fontSize: "12px" }}>{s.base_url}</code>
                  </td>
                  <td>
                    {s.api_key_var ? (
                      <EnvVarStatus
                        name={s.api_key_var}
                        status={envStatus.data?.[s.api_key_var]}
                      />
                    ) : (
                      <span style={{ color: "#999" }}>—</span>
                    )}
                  </td>
                  <td style={{ display: "flex", gap: "0.5rem" }}>
                    <button type="button" onClick={() => handleTest(s.id)}>
                      {t("discovery.test_button")}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(s.id, s.name)}
                      style={{ color: "red" }}
                    >
                      {t("discovery.delete_button")}
                    </button>
                    {test && (
                      <span
                        style={{
                          fontSize: "12px",
                          color: test.ok ? "green" : "red",
                          alignSelf: "center",
                        }}
                      >
                        {test.ok
                          ? `✅ ${t("discovery.test_ok")}`
                          : `❌ ${t("discovery.test_ko")} — ${test.detail}`}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
