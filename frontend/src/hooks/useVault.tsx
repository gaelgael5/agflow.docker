import React from "react";

// useVault.tsx — vault côté client supprimé, remplacé par Harpocrate (server-side).
// Ces stubs maintiennent la compatibilité des pages AgentEditorPage, DockerfilesPage
// et ProjectDetailPage qui n'ont pas encore migré vers Harpocrate.

type VaultState = "loading" | "uninitialized" | "locked" | "unlocked" | "error";

interface VaultContextValue {
  state: VaultState;
  lastError: string | null;
  setupVault: (passphrase: string) => Promise<void>;
  unlockVault: (passphrase: string) => Promise<boolean>;
  lockVault: () => void;
  encryptSecret: (plaintext: string) => { ciphertext: string; iv: string };
  decryptSecret: (ciphertext: string, iv: string) => string;
  refreshStatus: () => Promise<void>;
}

const noop = async () => {};
const noopSync = () => {};

const STUB: VaultContextValue = {
  state: "locked",
  lastError: null,
  setupVault: noop,
  unlockVault: async () => false,
  lockVault: noopSync,
  encryptSecret: () => { throw new Error("Vault removed — use Harpocrate"); },
  decryptSecret: () => { throw new Error("Vault removed — use Harpocrate"); },
  refreshStatus: noop,
};

export const useVault = (): VaultContextValue => STUB;

export const VaultProvider = ({ children }: { children: React.ReactNode }) =>
  React.createElement(React.Fragment, null, children);
