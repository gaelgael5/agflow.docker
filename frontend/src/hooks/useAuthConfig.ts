import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type AuthConfig,
  type AuthConfigUpdate,
  type AuthTestRequest,
  authConfigApi,
} from "@/lib/authConfigApi";

const AUTH_KEY = ["auth-config"] as const;

export function useAuthConfig() {
  const qc = useQueryClient();
  const query = useQuery<AuthConfig>({
    queryKey: AUTH_KEY,
    queryFn: () => authConfigApi.getConfig(),
  });
  const updateMutation = useMutation({
    mutationFn: (payload: AuthConfigUpdate) => authConfigApi.updateConfig(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: AUTH_KEY }),
  });
  const testMutation = useMutation({
    mutationFn: (payload: AuthTestRequest) => authConfigApi.testConnection(payload),
    // Pas d'invalidation — test ne modifie pas la conf
  });
  return { ...query, update: updateMutation, test: testMutation };
}
