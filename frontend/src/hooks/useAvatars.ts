import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  avatarsApi,
  type ThemeCreatePayload,
  type CharacterCreatePayload,
} from "@/lib/avatarsApi";

const THEMES_KEY = ["avatar-themes"] as const;
const themeKey = (slug: string) => ["avatar-theme", slug] as const;
const charKey = (theme: string, char: string) => ["avatar-char", theme, char] as const;

export function useAvatarThemes() {
  return useQuery({
    queryKey: THEMES_KEY,
    queryFn: () => avatarsApi.listThemes(),
  });
}

export function useAvatarTheme(slug: string | null) {
  return useQuery({
    queryKey: slug ? themeKey(slug) : ["avatar-theme", "none"],
    queryFn: () => avatarsApi.getTheme(slug!),
    enabled: Boolean(slug),
  });
}

export function useAvatarCharacter(theme: string | null, char: string | null) {
  return useQuery({
    queryKey: theme && char ? charKey(theme, char) : ["avatar-char", "none"],
    queryFn: () => avatarsApi.getCharacter(theme!, char!),
    enabled: Boolean(theme && char),
  });
}

export function useAvatarMutations(themeSlug: string | null) {
  const qc = useQueryClient();

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: THEMES_KEY });
    if (themeSlug) qc.invalidateQueries({ queryKey: themeKey(themeSlug) });
  };

  const createTheme = useMutation({
    mutationFn: (p: ThemeCreatePayload) => avatarsApi.createTheme(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: THEMES_KEY }),
  });

  const deleteTheme = useMutation({
    mutationFn: (slug: string) => avatarsApi.deleteTheme(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: THEMES_KEY }),
  });

  const createCharacter = useMutation({
    mutationFn: (p: CharacterCreatePayload) => avatarsApi.createCharacter(themeSlug!, p),
    onSuccess: invalidateAll,
  });

  const deleteCharacter = useMutation({
    mutationFn: (char: string) => avatarsApi.deleteCharacter(themeSlug!, char),
    onSuccess: invalidateAll,
  });

  return { createTheme, deleteTheme, createCharacter, deleteCharacter };
}
