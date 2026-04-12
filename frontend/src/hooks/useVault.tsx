import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  generateSalt,
  deriveKey,
  encrypt,
  decrypt,
  createTestProof,
  verifyPassphrase,
  bufferToBase64,
  base64ToBuffer,
} from "@/lib/vault";
import { vaultApi } from "@/lib/userSecretsApi";

type VaultState = "loading" | "uninitialized" | "locked" | "unlocked";

interface VaultContextValue {
  state: VaultState;
  setupVault: (passphrase: string) => Promise<void>;
  unlockVault: (passphrase: string) => Promise<boolean>;
  lockVault: () => void;
  encryptSecret: (plaintext: string) => Promise<{ ciphertext: string; iv: string }>;
  decryptSecret: (ciphertext: string, iv: string) => Promise<string>;
  refreshStatus: () => Promise<void>;
}

const VaultContext = createContext<VaultContextValue | null>(null);

export function VaultProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<VaultState>("loading");
  const keyRef = useRef<CryptoKey | null>(null);
  const saltRef = useRef<Uint8Array | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const status = await vaultApi.getStatus();
      if (!status.initialized) {
        setState("uninitialized");
      } else if (keyRef.current) {
        setState("unlocked");
      } else {
        setState("locked");
      }
    } catch {
      // Not logged in or network error — stay loading
      setState("loading");
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const setupVault = useCallback(async (passphrase: string) => {
    const salt = generateSalt();
    const key = await deriveKey(passphrase, salt);
    const proof = await createTestProof(key);
    await vaultApi.setup({
      salt: bufferToBase64(salt),
      test_ciphertext: proof.ciphertext,
      test_iv: proof.iv,
    });
    keyRef.current = key;
    saltRef.current = salt;
    setState("unlocked");
  }, []);

  const unlockVault = useCallback(async (passphrase: string): Promise<boolean> => {
    const status = await vaultApi.getStatus();
    if (!status.initialized || !status.salt || !status.test_ciphertext || !status.test_iv) {
      return false;
    }
    const salt = base64ToBuffer(status.salt);
    const key = await deriveKey(passphrase, salt);
    const ok = await verifyPassphrase(key, status.test_ciphertext, status.test_iv);
    if (!ok) return false;
    keyRef.current = key;
    saltRef.current = salt;
    setState("unlocked");
    return true;
  }, []);

  const lockVault = useCallback(() => {
    keyRef.current = null;
    saltRef.current = null;
    setState("locked");
  }, []);

  const encryptSecret = useCallback(async (plaintext: string) => {
    if (!keyRef.current) throw new Error("Vault is locked");
    return encrypt(keyRef.current, plaintext);
  }, []);

  const decryptSecret = useCallback(async (ciphertext: string, iv: string) => {
    if (!keyRef.current) throw new Error("Vault is locked");
    return decrypt(keyRef.current, ciphertext, iv);
  }, []);

  return (
    <VaultContext.Provider
      value={{ state, setupVault, unlockVault, lockVault, encryptSecret, decryptSecret, refreshStatus }}
    >
      {children}
    </VaultContext.Provider>
  );
}

export function useVault(): VaultContextValue {
  const ctx = useContext(VaultContext);
  if (!ctx) throw new Error("useVault must be used within VaultProvider");
  return ctx;
}
