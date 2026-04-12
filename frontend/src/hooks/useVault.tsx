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
  type VaultKey,
} from "@/lib/vault";
import { vaultApi } from "@/lib/userSecretsApi";

type VaultState = "loading" | "uninitialized" | "locked" | "unlocked";

interface VaultContextValue {
  state: VaultState;
  setupVault: (passphrase: string) => Promise<void>;
  unlockVault: (passphrase: string) => Promise<boolean>;
  lockVault: () => void;
  encryptSecret: (plaintext: string) => { ciphertext: string; iv: string };
  decryptSecret: (ciphertext: string, iv: string) => string;
  refreshStatus: () => Promise<void>;
}

const VaultContext = createContext<VaultContextValue | null>(null);

export function VaultProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<VaultState>("loading");
  const keyRef = useRef<VaultKey | null>(null);

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
      setState("loading");
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const setupVault = useCallback(async (passphrase: string) => {
    const salt = generateSalt();
    const key = deriveKey(passphrase, salt);
    const proof = createTestProof(key);
    await vaultApi.setup({
      salt: bufferToBase64(salt),
      test_ciphertext: proof.ciphertext,
      test_iv: proof.iv,
    });
    keyRef.current = key;
    setState("unlocked");
  }, []);

  const unlockVault = useCallback(async (passphrase: string): Promise<boolean> => {
    const status = await vaultApi.getStatus();
    if (!status.initialized || !status.salt || !status.test_ciphertext || !status.test_iv) {
      return false;
    }
    const salt = base64ToBuffer(status.salt);
    const key = deriveKey(passphrase, salt);
    const ok = verifyPassphrase(key, status.test_ciphertext, status.test_iv);
    if (!ok) return false;
    keyRef.current = key;
    setState("unlocked");
    return true;
  }, []);

  const lockVault = useCallback(() => {
    keyRef.current = null;
    setState("locked");
  }, []);

  const encryptSecret = useCallback((plaintext: string) => {
    if (!keyRef.current) throw new Error("Vault is locked");
    return encrypt(keyRef.current, plaintext);
  }, []);

  const decryptSecret = useCallback((ciphertext: string, iv: string) => {
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
