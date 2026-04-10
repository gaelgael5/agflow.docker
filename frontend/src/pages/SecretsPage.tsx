import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSecrets } from "@/hooks/useSecrets";
import { SecretForm } from "@/components/SecretForm";
import { RevealButton } from "@/components/RevealButton";
import { TestKeyButton } from "@/components/TestKeyButton";
import type { SecretCreate, SecretSummary } from "@/lib/secretsApi";

export function SecretsPage() {
  const { t } = useTranslation();
  const { secrets, isLoading, createMutation, deleteMutation } = useSecrets();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(payload: SecretCreate) {
    setError(null);
    try {
      await createMutation.mutateAsync(payload);
      setShowForm(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      setError(
        status === 409 ? t("secrets.error_duplicate") : t("secrets.error_generic"),
      );
    }
  }

  async function handleDelete(secret: SecretSummary) {
    const confirmed = window.confirm(
      t("secrets.confirm_delete", { name: secret.var_name }),
    );
    if (!confirmed) return;
    await deleteMutation.mutateAsync(secret.id);
  }

  return (
    <div style={{ padding: "2rem", maxWidth: 1100 }}>
      <h1>{t("secrets.page_title")}</h1>
      <p>{t("secrets.page_subtitle")}</p>

      <button
        type="button"
        onClick={() => setShowForm(true)}
        disabled={showForm}
        style={{ marginBottom: "1rem" }}
      >
        {t("secrets.add_button")}
      </button>

      {showForm && (
        <div style={{ marginBottom: "1.5rem" }}>
          <SecretForm
            mode="create"
            onSubmit={handleCreate}
            onCancel={() => {
              setShowForm(false);
              setError(null);
            }}
          />
          {error && (
            <p role="alert" style={{ color: "red" }}>
              {error}
            </p>
          )}
        </div>
      )}

      {isLoading ? (
        <p>{t("secrets.loading")}</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th>{t("secrets.col_name")}</th>
              <th>{t("secrets.col_value")}</th>
              <th>{t("secrets.col_scope")}</th>
              <th>{t("secrets.col_used_by")}</th>
              <th>{t("secrets.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {secrets?.map((secret) => (
              <tr key={secret.id} style={{ borderBottom: "1px solid #eee" }}>
                <td>
                  <code>{secret.var_name}</code>
                </td>
                <td>
                  <RevealButton secretId={secret.id} />
                </td>
                <td>
                  {secret.scope === "global"
                    ? t("secrets.scope_global")
                    : t("secrets.scope_agent")}
                </td>
                <td>
                  {secret.used_by.length === 0
                    ? t("secrets.none_used_by")
                    : secret.used_by.join(", ")}
                </td>
                <td style={{ display: "flex", gap: "0.5rem" }}>
                  <TestKeyButton secretId={secret.id} />
                  <button type="button" onClick={() => handleDelete(secret)}>
                    {t("secrets.delete")}
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
