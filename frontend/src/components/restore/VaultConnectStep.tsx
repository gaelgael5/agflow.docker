import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { restoreApi, type VaultSecretItem } from "@/lib/restoreApi";

interface VaultConnectStepProps {
  onDone: (vault: { url: string; apiKey: string }, secrets: VaultSecretItem[]) => void;
}

export function VaultConnectStep({ onDone }: VaultConnectStepProps): JSX.Element {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      await restoreApi.testVault(url, apiKey);
      const secrets = await restoreApi.listSecrets(url, apiKey, "");
      return secrets;
    },
    onSuccess: (secrets) => {
      onDone({ url, apiKey }, secrets);
    },
    onError: () => {
      toast.error(t("restore.vault_connect_error"));
    },
  });

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="vault-url">{t("restore.vault_url_label")}</Label>
        <Input
          id="vault-url"
          placeholder="https://vault.example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="vault-apikey">{t("restore.vault_apikey_label")}</Label>
        <Input
          id="vault-apikey"
          type="password"
          placeholder="•••••••••••••"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      <Button
        onClick={() => mutation.mutate()}
        disabled={!url || !apiKey || mutation.isPending}
      >
        {mutation.isPending ? t("common.loading") : t("restore.btn_connect_vault")}
      </Button>
    </div>
  );
}
