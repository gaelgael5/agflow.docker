import { useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";

/**
 * Hook that:
 * 1. Intercepts Ctrl+S to call `onSave`
 * 2. Shows beforeunload prompt when `isDirty` is true
 * 3. Returns a `guardedNavigate` wrapper that prompts before navigating
 */
export function useUnsavedGuard({
  isDirty,
  onSave,
}: {
  isDirty: boolean;
  onSave: () => void;
}) {
  const { t } = useTranslation();

  // Ctrl+S
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (isDirty) onSave();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isDirty, onSave]);

  // beforeunload
  useEffect(() => {
    if (!isDirty) return;
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  // Guard wrapper for SPA navigation
  const guardedAction = useCallback(
    (action: () => void) => {
      if (!isDirty) {
        action();
        return;
      }
      if (window.confirm(t("common.unsaved_changes"))) {
        action();
      }
    },
    [isDirty, t],
  );

  return { guardedAction };
}
