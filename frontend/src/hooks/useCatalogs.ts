import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  discoveryApi,
  mcpCatalogApi,
  skillsCatalogApi,
  type DiscoveryServiceCreate,
  type DiscoveryServiceSummary,
  type MCPServerSummary,
  type SkillSummary,
} from "@/lib/catalogsApi";

const DISCOVERY_KEY = ["discovery-services"] as const;
const MCP_KEY = ["mcp-catalog"] as const;
const SKILLS_KEY = ["skills-catalog"] as const;

export function useDiscoveryServices() {
  const qc = useQueryClient();

  const listQuery = useQuery<DiscoveryServiceSummary[]>({
    queryKey: DISCOVERY_KEY,
    queryFn: () => discoveryApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: DiscoveryServiceCreate) =>
      discoveryApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: DISCOVERY_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => discoveryApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: DISCOVERY_KEY }),
  });

  return {
    services: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    deleteMutation,
  };
}

export function useMCPCatalog() {
  const qc = useQueryClient();

  const listQuery = useQuery<MCPServerSummary[]>({
    queryKey: MCP_KEY,
    queryFn: () => mcpCatalogApi.list(),
  });

  const installMutation = useMutation({
    mutationFn: (payload: {
      discovery_service_id: string;
      package_id: string;
      recipes?: Record<string, unknown>;
      parameters?: unknown[];
    }) => mcpCatalogApi.install(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: MCP_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => mcpCatalogApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MCP_KEY }),
  });

  return {
    mcps: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    installMutation,
    deleteMutation,
  };
}

export function useSkillsCatalog() {
  const qc = useQueryClient();

  const listQuery = useQuery<SkillSummary[]>({
    queryKey: SKILLS_KEY,
    queryFn: () => skillsCatalogApi.list(),
  });

  const installMutation = useMutation({
    mutationFn: ({
      discoveryServiceId,
      skillId,
    }: {
      discoveryServiceId: string;
      skillId: string;
    }) => skillsCatalogApi.install(discoveryServiceId, skillId),
    onSuccess: () => qc.invalidateQueries({ queryKey: SKILLS_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => skillsCatalogApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SKILLS_KEY }),
  });

  return {
    skills: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    installMutation,
    deleteMutation,
  };
}
