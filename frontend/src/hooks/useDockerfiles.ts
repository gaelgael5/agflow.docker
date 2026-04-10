import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dockerfilesApi,
  type DockerfileCreate,
  type DockerfileDetail,
  type DockerfileSummary,
  type FileCreate,
} from "@/lib/dockerfilesApi";

const DOCKERFILES_KEY = ["dockerfiles"] as const;

export function useDockerfiles() {
  const qc = useQueryClient();

  const listQuery = useQuery<DockerfileSummary[]>({
    queryKey: DOCKERFILES_KEY,
    queryFn: () => dockerfilesApi.list(),
  });

  const invalidate = (id?: string) => {
    qc.invalidateQueries({ queryKey: DOCKERFILES_KEY });
    if (id) qc.invalidateQueries({ queryKey: ["dockerfile", id] });
  };

  const createMutation = useMutation({
    mutationFn: (payload: DockerfileCreate) => dockerfilesApi.create(payload),
    onSuccess: (data) => invalidate(data.id),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => dockerfilesApi.remove(id),
    onSuccess: (_data, id) => invalidate(id),
  });

  const createFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      payload,
    }: {
      dockerfileId: string;
      payload: FileCreate;
    }) => dockerfilesApi.createFile(dockerfileId, payload),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  const updateFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      fileId,
      content,
    }: {
      dockerfileId: string;
      fileId: string;
      content: string;
    }) => dockerfilesApi.updateFile(dockerfileId, fileId, content),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  const deleteFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      fileId,
    }: {
      dockerfileId: string;
      fileId: string;
    }) => dockerfilesApi.deleteFile(dockerfileId, fileId),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  return {
    dockerfiles: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    deleteMutation,
    createFileMutation,
    updateFileMutation,
    deleteFileMutation,
  };
}

export function useDockerfileDetail(id: string | null) {
  return useQuery<DockerfileDetail>({
    queryKey: ["dockerfile", id],
    queryFn: () => {
      if (!id) throw new Error("id required");
      return dockerfilesApi.get(id);
    },
    enabled: !!id,
  });
}
