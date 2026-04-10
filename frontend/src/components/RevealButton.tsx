import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { secretsApi } from "@/lib/secretsApi";

interface Props {
  secretId: string;
  autoHideMs?: number;
}

export function RevealButton({ secretId, autoHideMs = 10000 }: Props) {
  const { t } = useTranslation();
  const [value, setValue] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (value === null) return;
    const timer = setTimeout(() => setValue(null), autoHideMs);
    return () => clearTimeout(timer);
  }, [value, autoHideMs]);

  async function handleReveal() {
    setLoading(true);
    try {
      const res = await secretsApi.reveal(secretId);
      setValue(res.value);
    } finally {
      setLoading(false);
    }
  }

  function handleHide() {
    setValue(null);
  }

  return (
    <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
      <code>{value ?? t("secrets.value_masked")}</code>
      {value === null ? (
        <button type="button" onClick={handleReveal} disabled={loading}>
          {t("secrets.reveal")}
        </button>
      ) : (
        <button type="button" onClick={handleHide}>
          {t("secrets.hide")}
        </button>
      )}
    </span>
  );
}
