import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  backupsApi,
  type LocalBackup,
  type RemoteBackupFile,
  type RestoreResult,
} from "@/lib/backupsApi";

const LOCAL_BACKUPS_KEY = ["local-backups"] as const;
const remoteFilesKey = (connectionId: string | null) =>
  ["remote-backup-files", connectionId] as const;

export function useLocalBackups() {
  return useQuery<LocalBackup[]>({
    queryKey: LOCAL_BACKUPS_KEY,
    queryFn: () => backupsApi.listLocal(),
  });
}

export function useRemoteFiles(connectionId: string | null) {
  return useQuery<RemoteBackupFile[]>({
    queryKey: remoteFilesKey(connectionId),
    queryFn: () => {
      if (!connectionId) {
        return Promise.resolve([]);
      }
      return backupsApi.listRemoteFiles(connectionId);
    },
    enabled: !!connectionId,
  });
}

export function usePullMutation() {
  const qc = useQueryClient();
  return useMutation<
    LocalBackup,
    Error,
    { connectionId: string; filename: string }
  >({
    mutationFn: ({ connectionId, filename }) =>
      backupsApi.pullFromRemote(connectionId, filename),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LOCAL_BACKUPS_KEY });
    },
  });
}

export function useRestoreMutation() {
  return useMutation<
    RestoreResult,
    Error,
    { backupId: string; filename: string }
  >({
    mutationFn: ({ backupId, filename }) =>
      backupsApi.restoreLocal(backupId, filename),
  });
}
