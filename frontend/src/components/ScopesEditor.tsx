import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useScopes } from "@/hooks/useScopes";
import type { ScopeGroup } from "@/lib/apiKeysApi";

// ─── Props ────────────────────────────────────────────────────────────────────

export interface ScopesEditorProps {
  selected: string[];
  onChange: (scopes: string[]) => void;
  disabled?: boolean;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ScopesEditor({ selected, onChange, disabled }: ScopesEditorProps) {
  const { t } = useTranslation();
  const selectedSet = new Set(selected);

  const { groups, isLoading } = useScopes();

  function toggle(key: string) {
    if (disabled) return;
    const next = new Set(selectedSet);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    onChange([...next]);
  }

  function setGroup(group: ScopeGroup, value: boolean) {
    if (disabled || group.always_on) return;
    const next = new Set(selectedSet);
    for (const s of group.scopes) {
      if (value) {
        next.add(s);
      } else {
        next.delete(s);
      }
    }
    onChange([...next]);
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div className="max-h-[400px] overflow-y-auto space-y-4 pr-1">
      {groups.map((group) => {
        const allChecked = group.scopes.every((k) => selectedSet.has(k));
        const noneChecked = group.scopes.every((k) => !selectedSet.has(k));

        return (
          <div key={group.group}>
            {/* Group header */}
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex-1">
                {t(`scope_groups.${group.group}`)}
              </span>
              {!group.always_on && !disabled && (
                <div className="flex gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={`h-5 px-1.5 text-[10px] ${allChecked ? "text-primary" : "text-muted-foreground"}`}
                    onClick={() => setGroup(group, true)}
                  >
                    {t("scopes.all")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className={`h-5 px-1.5 text-[10px] ${noneChecked ? "text-primary" : "text-muted-foreground"}`}
                    onClick={() => setGroup(group, false)}
                  >
                    {t("scopes.none")}
                  </Button>
                </div>
              )}
            </div>

            {/* Scope rows */}
            <div className="space-y-1">
              {group.scopes.map((scope) => {
                const isAlwaysOn = group.always_on === true;
                const isChecked = selectedSet.has(scope);

                return (
                  <label
                    key={scope}
                    className={`flex items-start gap-3 py-0.5 rounded cursor-pointer hover:bg-muted/40 px-1 ${isAlwaysOn || disabled ? "cursor-not-allowed opacity-75" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggle(scope)}
                      disabled={isAlwaysOn || disabled}
                      className="mt-0.5 w-3.5 h-3.5 accent-primary cursor-pointer disabled:cursor-not-allowed shrink-0"
                    />
                    <span className="font-mono text-[11px] text-muted-foreground w-[200px] shrink-0 leading-5">
                      {scope}
                    </span>
                    <span className="text-[12px] leading-5 flex-1">
                      {t(`scope_descriptions.${scope}`)}
                    </span>
                  </label>
                );
              })}
            </div>

            {/* Separator */}
            <div className="mt-2 border-b border-border/40" />
          </div>
        );
      })}
    </div>
  );
}
