import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { Scope, SecretCreate } from "@/lib/secretsApi";

interface Props {
  mode: "create" | "edit";
  initialName?: string;
  initialScope?: Scope;
  onSubmit: (payload: SecretCreate) => Promise<void> | void;
  onCancel: () => void;
}

export function SecretForm({
  mode,
  initialName = "",
  initialScope = "global",
  onSubmit,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const [value, setValue] = useState("");
  const [scope] = useState<Scope>(initialScope);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({ var_name: name, value, scope });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        border: "1px solid #ccc",
        padding: "1rem",
        borderRadius: "4px",
        maxWidth: 480,
      }}
    >
      <h2>
        {mode === "create"
          ? t("secrets.form_title_new")
          : t("secrets.form_title_edit")}
      </h2>
      <div>
        <label>
          {t("secrets.col_name")}
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("secrets.form_name_placeholder")}
            disabled={mode === "edit"}
            required
          />
        </label>
      </div>
      <div>
        <label>
          {t("secrets.col_value")}
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t("secrets.form_value_placeholder")}
            required
          />
        </label>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
        <button type="submit" disabled={submitting}>
          {t("secrets.form_save")}
        </button>
        <button type="button" onClick={onCancel} disabled={submitting}>
          {t("secrets.form_cancel")}
        </button>
      </div>
    </form>
  );
}
