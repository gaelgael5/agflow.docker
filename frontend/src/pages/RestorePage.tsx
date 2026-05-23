// frontend/src/pages/RestorePage.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RestoreTimelineItem } from "@/components/restore/RestoreTimelineItem";
import { VaultConnectStep } from "@/components/restore/VaultConnectStep";
import { RemoteConnectionStep } from "@/components/restore/RemoteConnectionStep";
import { RemoteFileBrowser } from "@/components/restore/RemoteFileBrowser";
import type { VaultSecretItem } from "@/lib/restoreApi";

export interface RestoreWizardState {
  step: 1 | 2 | 3 | 4;
  vault: { url: string; apiKey: string } | null;
  secrets: VaultSecretItem[];
  connectionType: "sftp" | "s3" | "ftps" | "gdrive" | null;
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;
  selectedFile: { path: string; name: string; size_bytes: number | null } | null;
  jobId: string | null;
}

const INITIAL_STATE: RestoreWizardState = {
  step: 1,
  vault: null,
  secrets: [],
  connectionType: null,
  manualFields: {},
  vaultMappings: {},
  selectedFile: null,
  jobId: null,
};

export function RestorePage(): JSX.Element {
  const { t } = useTranslation();
  const [state, setState] = useState<RestoreWizardState>(INITIAL_STATE);

  function stepStatus(n: number): "pending" | "active" | "done" {
    if (state.step > n) return "done";
    if (state.step === n) return "active";
    return "pending";
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-8 space-y-1">
        <h1 className="text-2xl font-bold">{t("restore.page_title")}</h1>
        <p className="text-sm text-muted-foreground">{t("restore.page_subtitle")}</p>
      </div>

      <RestoreTimelineItem step={1} title={t("restore.step_vault")} status={stepStatus(1)}>
        <VaultConnectStep
          onDone={(vault, secrets) =>
            setState((s) => ({ ...s, step: 2, vault, secrets }))
          }
        />
      </RestoreTimelineItem>

      <RestoreTimelineItem step={2} title={t("restore.step_connection")} status={stepStatus(2)}>
        {state.vault && (
          <RemoteConnectionStep
            vaultUrl={state.vault.url}
            vaultApiKey={state.vault.apiKey}
            secrets={state.secrets}
            onDone={(cfg) =>
              setState((s) => ({
                ...s,
                step: 3,
                connectionType: cfg.type,
                manualFields: cfg.manual,
                vaultMappings: cfg.vault,
              }))
            }
          />
        )}
      </RestoreTimelineItem>

      <RestoreTimelineItem step={3} title={t("restore.step_browse")} status={stepStatus(3)}>
        {state.vault && state.connectionType && (
          <RemoteFileBrowser
            vaultUrl={state.vault.url}
            vaultApiKey={state.vault.apiKey}
            connectionType={state.connectionType}
            manualFields={state.manualFields}
            vaultMappings={state.vaultMappings}
            onSelect={(file) =>
              setState((s) => ({ ...s, step: 4, selectedFile: file }))
            }
          />
        )}
      </RestoreTimelineItem>

      <RestoreTimelineItem step={4} title={t("restore.step_confirm")} status={stepStatus(4)}>
        <p className="text-sm text-muted-foreground">étape 4 — à implémenter</p>
      </RestoreTimelineItem>
    </div>
  );
}
