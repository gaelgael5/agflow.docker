import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  backupSchedulesApi,
  type CreateFullPayload,
  type CreateSnapshotPayload,
  type FullScheduleSummary,
  type ScheduleHistoryEntry,
  type SnapshotScheduleSummary,
  type UpdateFullPayload,
  type UpdateSnapshotPayload,
} from "@/lib/backupSchedulesApi";

const FULL_KEY = ["backup-schedules", "full"] as const;
const SNAPSHOT_KEY = ["backup-schedules", "snapshot"] as const;
const REFETCH_MS = 30_000;

export function useFullSchedules() {
  const qc = useQueryClient();

  const listQuery = useQuery<FullScheduleSummary[]>({
    queryKey: FULL_KEY,
    queryFn: () => backupSchedulesApi.listFull(),
    refetchInterval: REFETCH_MS,
  });

  const createMutation = useMutation({
    mutationFn: (payload: CreateFullPayload) => backupSchedulesApi.createFull(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: FULL_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateFullPayload }) =>
      backupSchedulesApi.updateFull(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: FULL_KEY }),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => backupSchedulesApi.removeFull(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: FULL_KEY }),
  });

  const runNowMutation = useMutation({
    mutationFn: (id: string) => backupSchedulesApi.runFullNow(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: FULL_KEY }),
  });

  const setEnabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      backupSchedulesApi.setFullEnabled(id, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: FULL_KEY }),
  });

  return {
    schedules: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: removeMutation.mutateAsync,
    runNow: runNowMutation.mutateAsync,
    setEnabled: setEnabledMutation.mutateAsync,
  };
}

export function useSnapshotSchedules() {
  const qc = useQueryClient();

  const listQuery = useQuery<SnapshotScheduleSummary[]>({
    queryKey: SNAPSHOT_KEY,
    queryFn: () => backupSchedulesApi.listSnapshot(),
    refetchInterval: REFETCH_MS,
  });

  const createMutation = useMutation({
    mutationFn: (payload: CreateSnapshotPayload) => backupSchedulesApi.createSnapshot(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SNAPSHOT_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateSnapshotPayload }) =>
      backupSchedulesApi.updateSnapshot(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SNAPSHOT_KEY }),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => backupSchedulesApi.removeSnapshot(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SNAPSHOT_KEY }),
  });

  const runNowMutation = useMutation({
    mutationFn: (id: string) => backupSchedulesApi.runSnapshotNow(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SNAPSHOT_KEY }),
  });

  const setEnabledMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      backupSchedulesApi.setSnapshotEnabled(id, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: SNAPSHOT_KEY }),
  });

  return {
    schedules: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    create: createMutation.mutateAsync,
    update: updateMutation.mutateAsync,
    remove: removeMutation.mutateAsync,
    runNow: runNowMutation.mutateAsync,
    setEnabled: setEnabledMutation.mutateAsync,
  };
}

export function useFullScheduleHistory(scheduleId: string | undefined, enabled = true) {
  return useQuery<ScheduleHistoryEntry[]>({
    queryKey: ["backup-schedules", "full", scheduleId, "history"],
    queryFn: () => {
      if (!scheduleId) throw new Error("scheduleId required");
      return backupSchedulesApi.listFullHistory(scheduleId);
    },
    enabled: enabled && !!scheduleId,
  });
}

export function useSnapshotScheduleHistory(scheduleId: string | undefined, enabled = true) {
  return useQuery<ScheduleHistoryEntry[]>({
    queryKey: ["backup-schedules", "snapshot", scheduleId, "history"],
    queryFn: () => {
      if (!scheduleId) throw new Error("scheduleId required");
      return backupSchedulesApi.listSnapshotHistory(scheduleId);
    },
    enabled: enabled && !!scheduleId,
  });
}
