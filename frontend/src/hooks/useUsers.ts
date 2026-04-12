import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  usersApi,
  type UserCreate,
  type UserSummary,
  type UserUpdate,
} from "@/lib/usersApi";

const USERS_KEY = ["users"] as const;

export function useUsers() {
  const qc = useQueryClient();

  const listQuery = useQuery<UserSummary[]>({
    queryKey: USERS_KEY,
    queryFn: () => usersApi.list(),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: USERS_KEY });
  };

  const createMutation = useMutation({
    mutationFn: (payload: UserCreate) => usersApi.create(payload),
    onSuccess: invalidate,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UserUpdate }) =>
      usersApi.update(id, payload),
    onSuccess: invalidate,
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => usersApi.approve(id),
    onSuccess: invalidate,
  });

  const disableMutation = useMutation({
    mutationFn: (id: string) => usersApi.disable(id),
    onSuccess: invalidate,
  });

  const enableMutation = useMutation({
    mutationFn: (id: string) => usersApi.enable(id),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => usersApi.remove(id),
    onSuccess: invalidate,
  });

  return {
    users: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    approveMutation,
    disableMutation,
    enableMutation,
    deleteMutation,
  };
}

export function useUserDetail(id: string | null) {
  return useQuery<UserSummary>({
    queryKey: ["user", id],
    queryFn: () => {
      if (!id) throw new Error("id required");
      return usersApi.get(id);
    },
    enabled: !!id,
  });
}
