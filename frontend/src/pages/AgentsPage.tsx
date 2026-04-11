import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAgents } from "@/hooks/useAgents";
import { slugify } from "@/lib/slugify";

export function AgentsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { agents, isLoading, deleteMutation, duplicateMutation } = useAgents();

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(t("agents.confirm_delete", { name }))) return;
    await deleteMutation.mutateAsync(id);
  }

  async function handleDuplicate(id: string) {
    const displayName = window.prompt(t("agents.duplicate_prompt_name"));
    if (!displayName) return;
    const slug = window.prompt(
      t("agents.duplicate_prompt_slug"),
      slugify(displayName, "-"),
    );
    if (!slug) return;
    await duplicateMutation.mutateAsync({ id, slug, displayName });
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ padding: "2rem", maxWidth: 1200 }}>
      <h1>{t("agents.page_title")}</h1>
      <p>{t("agents.page_subtitle")}</p>

      <button
        type="button"
        onClick={() => navigate("/agents/new")}
        style={{ marginBottom: "1rem" }}
      >
        {t("agents.add_button")}
      </button>

      {(agents ?? []).length === 0 ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("agents.no_agents")}
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th>{t("agents.col_slug")}</th>
              <th>{t("agents.col_name")}</th>
              <th>{t("agents.col_dockerfile")}</th>
              <th>{t("agents.col_role")}</th>
              <th>{t("agents.col_status")}</th>
              <th>{t("agents.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {agents?.map((a) => (
              <tr key={a.id} style={{ borderBottom: "1px solid #eee" }}>
                <td>
                  <code>{a.slug}</code>
                </td>
                <td>{a.display_name}</td>
                <td>
                  <code style={{ fontSize: "12px" }}>{a.dockerfile_id}</code>
                </td>
                <td>
                  <code style={{ fontSize: "12px" }}>{a.role_id}</code>
                </td>
                <td>
                  {a.has_errors ? (
                    <span
                      style={{
                        fontSize: "11px",
                        color: "#991b1b",
                        background: "#fef2f2",
                        border: "1px solid #fca5a5",
                        padding: "2px 6px",
                        borderRadius: "10px",
                      }}
                    >
                      {t("agents.error_badge")}
                    </span>
                  ) : (
                    <span style={{ color: "#999", fontSize: "12px" }}>—</span>
                  )}
                </td>
                <td style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    type="button"
                    onClick={() => navigate(`/agents/${a.id}`)}
                  >
                    {t("agents.edit_button")}
                  </button>
                  <button type="button" onClick={() => handleDuplicate(a.id)}>
                    {t("agents.duplicate_button")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(a.id, a.display_name)}
                    style={{ color: "red" }}
                  >
                    {t("agents.delete_button")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
