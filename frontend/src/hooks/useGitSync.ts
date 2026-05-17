import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  gitSyncApi,
  type GitSyncCommit,
  type GitSyncConfig,
  type GitSyncConfigUpsert,
  type GitSyncExportResult,
  type GitSyncImportPreview,
  type GitSyncImportResult,
  type GitSyncTestSecretRefResult,
} from "@/lib/gitSyncApi";

const KEY_CONFIG = ["git-sync", "config"] as const;
const KEY_TABLES = ["git-sync", "available-tables"] as const;
const KEY_COMMITS_BASE = ["git-sync", "commits"] as const;
const commitsKey = (limit: number) =>
  ["git-sync", "commits", limit] as const;

export function useGitSyncConfig() {
  return useQuery<GitSyncConfig | null>({
    queryKey: KEY_CONFIG,
    queryFn: () => gitSyncApi.fetchConfig(),
    refetchInterval: 30_000,
  });
}

export function useAvailableTables() {
  return useQuery<string[]>({
    queryKey: KEY_TABLES,
    queryFn: () => gitSyncApi.listAvailableTables(),
    staleTime: 5 * 60_000,
  });
}

export function useGitSyncCommits(limit = 30, enabled = true) {
  return useQuery<GitSyncCommit[]>({
    queryKey: commitsKey(limit),
    queryFn: () => gitSyncApi.listCommits(limit),
    refetchInterval: 60_000,
    enabled,
  });
}

export function useUpsertConfig() {
  const qc = useQueryClient();
  return useMutation<GitSyncConfig, Error, GitSyncConfigUpsert>({
    mutationFn: (payload) => gitSyncApi.upsertConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}

export function useDeleteConfig() {
  const qc = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: () => gitSyncApi.deleteConfig(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}

export function useTestSecretRef() {
  return useMutation<GitSyncTestSecretRefResult, Error, string>({
    mutationFn: (authSecretRef) => gitSyncApi.testSecretRef(authSecretRef),
  });
}

export function useRunExport() {
  const qc = useQueryClient();
  return useMutation<GitSyncExportResult, Error, void>({
    mutationFn: () => gitSyncApi.runExport(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
      qc.invalidateQueries({ queryKey: KEY_COMMITS_BASE });
    },
  });
}

export function usePreviewImport() {
  return useMutation<GitSyncImportPreview, Error, void>({
    mutationFn: () => gitSyncApi.previewImport(),
  });
}

export function useRunImport() {
  const qc = useQueryClient();
  return useMutation<GitSyncImportResult, Error, void>({
    mutationFn: () => gitSyncApi.runImport(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}
