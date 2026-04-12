import { gcm } from "@noble/ciphers/aes.js";
import { randomBytes } from "@noble/ciphers/utils.js";
import { pbkdf2 } from "@noble/hashes/pbkdf2.js";
import { sha256 } from "@noble/hashes/sha2.js";

const VAULT_TEST_PLAINTEXT = "VAULT_OK";
const PBKDF2_ITERATIONS = 100_000;
const KEY_LENGTH = 32; // 256 bits

export type VaultKey = Uint8Array;

export function generateSalt(): Uint8Array {
  return randomBytes(16);
}

export function deriveKey(passphrase: string, salt: Uint8Array): VaultKey {
  return pbkdf2(sha256, new TextEncoder().encode(passphrase), salt, {
    c: PBKDF2_ITERATIONS,
    dkLen: KEY_LENGTH,
  });
}

export function encrypt(
  key: VaultKey,
  plaintext: string,
): { ciphertext: string; iv: string } {
  const iv = randomBytes(12);
  const encoded = new TextEncoder().encode(plaintext);
  const aes = gcm(key, iv);
  const encrypted = aes.encrypt(encoded);
  return {
    ciphertext: bufferToBase64(encrypted),
    iv: bufferToBase64(iv),
  };
}

export function decrypt(
  key: VaultKey,
  ciphertext: string,
  iv: string,
): string {
  const aes = gcm(key, base64ToBuffer(iv));
  const decrypted = aes.decrypt(base64ToBuffer(ciphertext));
  return new TextDecoder().decode(decrypted);
}

export function createTestProof(
  key: VaultKey,
): { ciphertext: string; iv: string } {
  return encrypt(key, VAULT_TEST_PLAINTEXT);
}

export function verifyPassphrase(
  key: VaultKey,
  testCiphertext: string,
  testIv: string,
): boolean {
  try {
    return decrypt(key, testCiphertext, testIv) === VAULT_TEST_PLAINTEXT;
  } catch {
    return false;
  }
}

export function bufferToBase64(buf: Uint8Array): string {
  let binary = "";
  for (const b of buf) binary += String.fromCharCode(b);
  return btoa(binary);
}

export function base64ToBuffer(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
