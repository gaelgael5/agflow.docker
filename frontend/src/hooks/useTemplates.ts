import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { templatesApi, type TemplateSummary } from "@/lib/templatesApi";

const TEMPLATES_KEY = ["templates"] as const;

export function useTemplates() {
  const qc = useQueryClient();

  const listQuery = useQuery<TemplateSummary[]>({
    queryKey: TEMPLATES_KEY,
    queryFn: () => templatesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { slug: string; display_name: string; description?: string }) =>
      templatesApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => templatesApi.remove(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  });

  return {
    templates: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
