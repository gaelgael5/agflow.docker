import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { secretsApi } from "@/lib/secretsApi";
import { userSecretsApi } from "@/lib/userSecretsApi";
import { extractPlaceholders } from "@/lib/envPlaceholders";

interface UseEmptyLaunchKeysParams {
  dockerfileJsonContent: string | null | undefined;
  decryptedSecrets: Record<string, string> | null | undefined;
}

interface UseEmptyLaunchKeysResult {
  emptyKeys: string[];
  isLoading: boolean;
}

/**
 * Inspects ${VAR} placeholders in a Dockerfile.json content and returns the
 * subset that will be empty at container launch time.
 *
 * A placeholder is considered NON empty if at least one of these holds:
 *   1. it has a non-empty value in the decrypted user vault dict, OR
 *   2. it exists by name in the user vault (even if not yet decrypted —
 *      handleRunContainer decrypts on click), OR
 *   3. the global platform secrets table reports it as "ok".
 *
 * Without (2), opening the page before the auto-decrypt effect runs produces
 * a false-positive warning even though launch will correctly inject the value.
 */
export function useEmptyLaunchKeys({
  dockerfileJsonContent,
  decryptedSecrets,
}: UseEmptyLaunchKeysParams): UseEmptyLaunchKeysResult {
  const placeholders = useMemo(
    () => extractPlaceholders(dockerfileJsonContent ?? ""),
    [dockerfileJsonContent],
  );

  const { data: platformStatus, isLoading: platformLoading } = useQuery({
    queryKey: ["secrets-resolve-status", placeholders],
    queryFn: () => secretsApi.resolveStatus(placeholders),
    enabled: placeholders.length > 0,
    staleTime: 30_000,
  });

  // Names of secrets the user has stored in their vault (encrypted at rest).
  // We only need the names — values get decrypted at launch time.
  const { data: userSecretsList, isLoading: vaultListLoading } = useQuery({
    queryKey: ["user-secrets-names"],
    queryFn: () => userSecretsApi.list(),
    enabled: placeholders.length > 0,
    staleTime: 30_000,
  });

  const emptyKeys = useMemo(() => {
    if (placeholders.length === 0) return [];
    const userValues = decryptedSecrets ?? {};
    const status = platformStatus ?? {};
    const vaultNames = new Set((userSecretsList ?? []).map((s) => s.name));
    return placeholders.filter((name) => {
      const fromUser = userValues[name];
      if (typeof fromUser === "string" && fromUser.length > 0) return false;
      if (vaultNames.has(name)) return false;
      if (status[name] === "ok") return false;
      return true;
    });
  }, [placeholders, decryptedSecrets, platformStatus, userSecretsList]);

  return { emptyKeys, isLoading: platformLoading || vaultListLoading };
}
