import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type BasebackupSummary,
  type CloneStatusOut,
  type CloneStatusValue,
  type PitrConfig,
  type PitrConfigUpdate,
  pitrApi,
  type RestoreWindow,
  type WalStatus,
} from "@/lib/pitrApi";

const CONFIG_KEY = ["pitr", "config"] as const;
const BASEBACKUPS_KEY = ["pitr", "basebackups"] as const;
const WAL_STATUS_KEY = ["pitr", "wal-status"] as const;
const RESTORE_WINDOW_KEY = ["pitr", "restore-window"] as const;
const ACTIVE_CLONE_KEY = ["pitr", "clones", "active"] as const;

const REFETCH_LIST_MS = 30_000;
const REFETCH_WAL_MS = 10_000;
const REFETCH_CLONE_FAST_MS = 2_000;
const REFETCH_CLONE_READY_MS = 30_000;

export function usePitrConfig() {
  const qc = useQueryClient();
  const query = useQuery<PitrConfig>({
    queryKey: CONFIG_KEY,
    queryFn: () => pitrApi.getConfig(),
  });
  const updateMutation = useMutation({
    mutationFn: (payload: PitrConfigUpdate) => pitrApi.updateConfig(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONFIG_KEY }),
  });
  return { ...query, update: updateMutation };
}

export function usePitrBasebackups() {
  const qc = useQueryClient();
  const query = useQuery<BasebackupSummary[]>({
    queryKey: BASEBACKUPS_KEY,
    queryFn: () => pitrApi.listBasebackups(),
    refetchInterval: REFETCH_LIST_MS,
  });
  const triggerMutation = useMutation({
    mutationFn: () => pitrApi.triggerBasebackup(),
    onSuccess: () => qc.invalidateQueries({ queryKey: BASEBACKUPS_KEY }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => pitrApi.deleteBasebackup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: BASEBACKUPS_KEY }),
  });
  const pushMutation = useMutation({
    mutationFn: ({ basebackupId, remoteId }: { basebackupId: string; remoteId: string }) =>
      pitrApi.pushBasebackup(basebackupId, remoteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: BASEBACKUPS_KEY }),
  });
  return {
    ...query,
    trigger: triggerMutation,
    remove: deleteMutation,
    push: pushMutation,
  };
}

export function usePitrWalStatus() {
  return useQuery<WalStatus>({
    queryKey: WAL_STATUS_KEY,
    queryFn: () => pitrApi.getWalStatus(),
    refetchInterval: REFETCH_WAL_MS,
  });
}

export function usePitrRestoreWindow() {
  return useQuery<RestoreWindow>({
    queryKey: RESTORE_WINDOW_KEY,
    queryFn: () => pitrApi.getRestoreWindow(),
    refetchInterval: REFETCH_LIST_MS,
    retry: false, // 404 quand aucun basebackup — pas la peine de retenter
  });
}

function refetchIntervalForClone(status: CloneStatusValue | undefined): number | false {
  if (!status) return REFETCH_CLONE_FAST_MS;
  if (status === "restoring" || status === "terminating") return REFETCH_CLONE_FAST_MS;
  if (status === "ready") return REFETCH_CLONE_READY_MS;
  // terminated, failed: stop polling
  return false;
}

export function usePitrActiveClone() {
  const qc = useQueryClient();
  const query = useQuery<CloneStatusOut | null>({
    queryKey: ACTIVE_CLONE_KEY,
    queryFn: () => pitrApi.getActiveClone(),
    refetchInterval: (q) => refetchIntervalForClone(q.state.data?.status),
  });
  const startMutation = useMutation({
    mutationFn: (targetTimeIso: string) => pitrApi.startClone(targetTimeIso),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACTIVE_CLONE_KEY }),
  });
  const extendMutation = useMutation({
    mutationFn: () => pitrApi.extendActiveClone(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACTIVE_CLONE_KEY }),
  });
  const terminateMutation = useMutation({
    mutationFn: () => pitrApi.terminateActiveClone(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ACTIVE_CLONE_KEY }),
  });
  return {
    ...query,
    start: startMutation,
    extend: extendMutation,
    terminate: terminateMutation,
  };
}
