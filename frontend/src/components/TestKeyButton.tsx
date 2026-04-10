import { useState } from "react";
import { useTranslation } from "react-i18next";
import { secretsApi, type SecretTestResult } from "@/lib/secretsApi";

interface Props {
  secretId: string;
}

export function TestKeyButton({ secretId }: Props) {
  const { t } = useTranslation();
  const [result, setResult] = useState<SecretTestResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleTest() {
    setLoading(true);
    try {
      const res = await secretsApi.test(secretId);
      setResult(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <span>
      <button type="button" onClick={handleTest} disabled={loading}>
        {t("secrets.test")}
      </button>
      {result && (
        <span style={{ marginLeft: "0.5rem" }}>
          {!result.supported
            ? `⚠️ ${t("secrets.test_unsupported")}`
            : result.ok
              ? `✅ ${t("secrets.test_ok")}`
              : `❌ ${t("secrets.test_ko")} — ${result.detail}`}
        </span>
      )}
    </span>
  );
}
