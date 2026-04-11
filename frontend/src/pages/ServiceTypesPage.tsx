import { useTranslation } from "react-i18next";
import { useServiceTypes } from "@/hooks/useServiceTypes";
import { slugify } from "@/lib/slugify";

export function ServiceTypesPage() {
  const { t } = useTranslation();
  const { serviceTypes, isLoading, createMutation, deleteMutation } =
    useServiceTypes();

  async function handleAdd() {
    const display_name = window.prompt(t("service_types.prompt_display_name"));
    if (!display_name) return;
    const name = window.prompt(
      t("service_types.prompt_name"),
      slugify(display_name),
    );
    if (!name) return;
    try {
      await createMutation.mutateAsync({ name, display_name });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      window.alert(detail ?? t("service_types.error_generic"));
    }
  }

  async function handleDelete(name: string, display_name: string) {
    if (!window.confirm(t("service_types.confirm_delete", { name: display_name })))
      return;
    try {
      await deleteMutation.mutateAsync(name);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      window.alert(detail ?? t("service_types.error_generic"));
    }
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ padding: "2rem", maxWidth: 900 }}>
      <h1>{t("service_types.page_title")}</h1>
      <p>{t("service_types.page_subtitle")}</p>

      <button
        type="button"
        onClick={handleAdd}
        style={{ marginBottom: "1rem" }}
      >
        {t("service_types.add_button")}
      </button>

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
            <th>{t("service_types.col_display_name")}</th>
            <th>{t("service_types.col_name")}</th>
            <th>{t("service_types.col_type")}</th>
            <th>{t("service_types.col_actions")}</th>
          </tr>
        </thead>
        <tbody>
          {(serviceTypes ?? []).map((st) => (
            <tr key={st.name} style={{ borderBottom: "1px solid #eee" }}>
              <td>{st.display_name}</td>
              <td>
                <code style={{ fontSize: "12px" }}>{st.name}</code>
              </td>
              <td>
                {st.is_native ? (
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 6px",
                      background: "#e0e7ff",
                      borderRadius: "3px",
                    }}
                  >
                    {t("service_types.native")}
                  </span>
                ) : (
                  <span style={{ fontSize: "11px", color: "#666" }}>
                    {t("service_types.custom")}
                  </span>
                )}
              </td>
              <td>
                {st.is_native ? (
                  <span style={{ color: "#999", fontSize: "12px" }}>—</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleDelete(st.name, st.display_name)}
                    style={{ color: "red" }}
                  >
                    {t("service_types.delete_button")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
