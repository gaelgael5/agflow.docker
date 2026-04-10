import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  rolesApi,
  type DocumentCreate,
  type DocumentUpdate,
  type RoleDetail,
} from "@/lib/rolesApi";

export function useRoleDetail(roleId: string | null) {
  return useQuery<RoleDetail>({
    queryKey: ["role", roleId],
    queryFn: () => {
      if (!roleId) throw new Error("roleId required");
      return rolesApi.get(roleId);
    },
    enabled: !!roleId,
  });
}

export function useRoleDocumentMutations(roleId: string) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["role", roleId] });

  const createDoc = useMutation({
    mutationFn: (payload: DocumentCreate) =>
      rolesApi.createDocument(roleId, payload),
    onSuccess: invalidate,
  });

  const updateDoc = useMutation({
    mutationFn: ({ docId, payload }: { docId: string; payload: DocumentUpdate }) =>
      rolesApi.updateDocument(roleId, docId, payload),
    onSuccess: invalidate,
  });

  const deleteDoc = useMutation({
    mutationFn: (docId: string) => rolesApi.deleteDocument(roleId, docId),
    onSuccess: invalidate,
  });

  return { createDoc, updateDoc, deleteDoc };
}
