import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
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
    <form onSubmit={handleSubmit} className="space-y-4 max-w-[480px]">
      <h2 className="text-sm font-semibold text-foreground">
        {mode === "create"
          ? t("secrets.form_title_new")
          : t("secrets.form_title_edit")}
      </h2>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="secret-name">{t("secrets.col_name")}</Label>
        <Input
          id="secret-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("secrets.form_name_placeholder")}
          disabled={mode === "edit"}
          required
          className="font-mono text-[12px]"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="secret-value">{t("secrets.col_value")}</Label>
        <Input
          id="secret-value"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t("secrets.form_value_placeholder")}
          required
        />
      </div>

      <div className="flex gap-2 pt-2">
        <Button type="submit" disabled={submitting}>
          {t("secrets.form_save")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={submitting}
        >
          {t("secrets.form_cancel")}
        </Button>
      </div>
    </form>
  );
}
