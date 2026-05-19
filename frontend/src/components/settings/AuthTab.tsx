import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { useAuthConfig } from "@/hooks/useAuthConfig";
import { type AuthTestResult } from "@/lib/authConfigApi";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Vault {
  id: string;
  name: string;
  url: string;
  is_default: boolean;
}

export function AuthTab() {
  const { t } = useTranslation();
  const { data: cfg, update, test } = useAuthConfig();
  const vaultsQuery = useQuery<Vault[]>({
    queryKey: ["harpocrate-vaults"],
    queryFn: () => api.get<Vault[]>("/admin/harpocrate-vaults").then((r) => r.data),
  });

  const [mode, setMode] = useState<"local" | "keycloak">("local");
  const [kcUrl, setKcUrl] = useState("");
  const [realm, setRealm] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [vaultName, setVaultName] = useState("default");
  const [testResult, setTestResult] = useState<AuthTestResult | null>(null);

  useEffect(() => {
    if (cfg) {
      setMode(cfg.mode);
      setKcUrl(cfg.keycloak_url);
      setRealm(cfg.keycloak_realm);
      setClientId(cfg.keycloak_client_id);
      setVaultName(cfg.vault_name);
      // Ne pas pré-remplir clientSecret — placeholder dynamique
    }
  }, [cfg]);

  const isKeycloakMode = mode === "keycloak";

  const onTest = () => {
    setTestResult(null);
    test.mutate(
      {
        keycloak_url: kcUrl,
        keycloak_realm: realm,
        keycloak_client_id: clientId,
        keycloak_client_secret: clientSecret || undefined,
        vault_name: vaultName,
      },
      { onSuccess: (res) => setTestResult(res) },
    );
  };

  const onSave = () => {
    update.mutate(
      {
        mode,
        keycloak_url: kcUrl,
        keycloak_realm: realm,
        keycloak_client_id: clientId,
        keycloak_client_secret: clientSecret || undefined,
        vault_name: vaultName,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.auth.toast_saved"));
          setClientSecret(""); // reset le champ secret après save réussi
        },
        onError: (err) => {
          toast.error(`${t("settings.auth.toast_save_error")} : ${(err as Error).message}`);
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">{t("settings.auth.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("settings.auth.subtitle")}</p>
      </div>

      <div className="space-y-2">
        <Label>{t("settings.auth.mode_label")}</Label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="auth-mode"
              value="local"
              checked={mode === "local"}
              onChange={() => setMode("local")}
            />
            {t("settings.auth.mode_local")}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="auth-mode"
              value="keycloak"
              checked={mode === "keycloak"}
              onChange={() => setMode("keycloak")}
            />
            {t("settings.auth.mode_keycloak")}
          </label>
        </div>
      </div>

      <fieldset
        disabled={!isKeycloakMode}
        className={`space-y-3 rounded border p-4 ${isKeycloakMode ? "" : "opacity-50"}`}
      >
        <legend className="px-2 text-sm font-medium">
          {t("settings.auth.keycloak_section")}
        </legend>
        <div className="space-y-1.5">
          <Label htmlFor="kc-url">{t("settings.auth.keycloak_url")}</Label>
          <Input
            id="kc-url"
            type="url"
            value={kcUrl}
            onChange={(e) => setKcUrl(e.target.value)}
            placeholder="https://keycloak.example.com"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-realm">{t("settings.auth.keycloak_realm")}</Label>
          <Input
            id="kc-realm"
            value={realm}
            onChange={(e) => setRealm(e.target.value)}
            placeholder="yoops"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-cid">{t("settings.auth.keycloak_client_id")}</Label>
          <Input
            id="kc-cid"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="agflow-docker"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-secret">{t("settings.auth.keycloak_client_secret")}</Label>
          <Input
            id="kc-secret"
            type="password"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            placeholder={
              cfg?.has_secret
                ? t("settings.auth.secret_keep")
                : t("settings.auth.secret_required")
            }
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">
            &#9432; {t("settings.auth.secret_hint_vault")}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-vault">{t("settings.auth.vault_name")}</Label>
          <select
            id="kc-vault"
            value={vaultName}
            onChange={(e) => setVaultName(e.target.value)}
            className="w-full rounded border px-2 py-1.5"
          >
            {vaultsQuery.data?.map((v) => (
              <option key={v.id} value={v.name}>
                {v.name}
                {v.is_default ? " (défaut)" : ""}
              </option>
            ))}
          </select>
        </div>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={!isKeycloakMode || test.isPending}
          onClick={onTest}
        >
          {t("settings.auth.test_button")}
        </Button>
        <Button onClick={onSave} disabled={update.isPending}>
          {t("settings.auth.save_button")}
        </Button>
      </div>

      {testResult && (
        <div className="space-y-1 rounded border p-3 text-sm">
          <p className="font-medium">{t("settings.auth.test_result_title")}</p>
          <p>
            {testResult.discovery_ok ? "✓" : "✗"}{" "}
            {testResult.discovery_ok
              ? t("settings.auth.test_discovery_ok")
              : t("settings.auth.test_discovery_ko")}
          </p>
          <p>
            {testResult.token_ok ? "✓" : "✗"}{" "}
            {testResult.token_ok
              ? t("settings.auth.test_token_ok")
              : t("settings.auth.test_token_ko")}
          </p>
          {testResult.ok ? (
            <p className="text-green-600">&#8594; {t("settings.auth.test_done")}</p>
          ) : (
            <p className="text-destructive">&#8594; {testResult.detail}</p>
          )}
        </div>
      )}
    </div>
  );
}
