import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

// ─── Scope catalogue ──────────────────────────────────────────────────────────

interface ScopeInfo {
  key: string;
}

interface ScopeGroup {
  id: string;
  scopes: ScopeInfo[];
  alwaysOn?: boolean;
}

const SCOPE_GROUPS: ScopeGroup[] = [
  {
    id: "platform_secrets",
    scopes: [{ key: "platform_secrets:read" }, { key: "platform_secrets:write" }],
  },
  {
    id: "user_secrets",
    scopes: [{ key: "user_secrets:read" }, { key: "user_secrets:write" }],
  },
  {
    id: "dockerfiles",
    scopes: [
      { key: "dockerfiles:read" },
      { key: "dockerfiles:write" },
      { key: "dockerfiles:delete" },
      { key: "dockerfiles:build" },
    ],
  },
  {
    id: "dockerfiles.files",
    scopes: [
      { key: "dockerfiles.files:read" },
      { key: "dockerfiles.files:write" },
      { key: "dockerfiles.files:delete" },
    ],
  },
  {
    id: "dockerfiles.params",
    scopes: [
      { key: "dockerfiles.params:read" },
      { key: "dockerfiles.params:write" },
    ],
  },
  {
    id: "discovery",
    scopes: [{ key: "discovery:read" }, { key: "discovery:write" }],
  },
  {
    id: "service_types",
    scopes: [{ key: "service_types:read" }, { key: "service_types:write" }],
  },
  {
    id: "users",
    scopes: [{ key: "users:manage" }],
  },
  {
    id: "roles",
    scopes: [
      { key: "roles:read" },
      { key: "roles:write" },
      { key: "roles:delete" },
    ],
  },
  {
    id: "catalogs",
    scopes: [{ key: "catalogs:read" }, { key: "catalogs:write" }],
  },
  {
    id: "agents",
    scopes: [
      { key: "agents:read" },
      { key: "agents:write" },
      { key: "agents:delete" },
      { key: "agents:run" },
    ],
  },
  {
    id: "containers",
    scopes: [
      { key: "containers:read" },
      { key: "containers:run" },
      { key: "containers:stop" },
    ],
  },
  {
    id: "containers.logs",
    scopes: [{ key: "containers.logs:read" }],
  },
  {
    id: "containers.chat",
    scopes: [{ key: "containers.chat:write" }],
  },
  {
    id: "keys",
    scopes: [{ key: "keys:manage" }],
    alwaysOn: true,
  },
];

export const ALL_SCOPES: string[] = SCOPE_GROUPS.flatMap((g) =>
  g.scopes.map((s) => s.key),
);

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
    if (disabled || group.alwaysOn) return;
    const next = new Set(selectedSet);
    for (const s of group.scopes) {
      if (value) {
        next.add(s.key);
      } else {
        next.delete(s.key);
      }
    }
    onChange([...next]);
  }

  return (
    <div className="max-h-[400px] overflow-y-auto space-y-4 pr-1">
      {SCOPE_GROUPS.map((group) => {
        const groupScopes = group.scopes.map((s) => s.key);
        const allChecked = groupScopes.every((k) => selectedSet.has(k));
        const noneChecked = groupScopes.every((k) => !selectedSet.has(k));

        return (
          <div key={group.id}>
            {/* Group header */}
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex-1">
                {t(`scope_groups.${group.id}`)}
              </span>
              {!group.alwaysOn && !disabled && (
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
                const isAlwaysOn = group.alwaysOn === true;
                const isChecked = selectedSet.has(scope.key);

                return (
                  <label
                    key={scope.key}
                    className={`flex items-start gap-3 py-0.5 rounded cursor-pointer hover:bg-muted/40 px-1 ${isAlwaysOn || disabled ? "cursor-not-allowed opacity-75" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggle(scope.key)}
                      disabled={isAlwaysOn || disabled}
                      className="mt-0.5 w-3.5 h-3.5 accent-primary cursor-pointer disabled:cursor-not-allowed shrink-0"
                    />
                    <span className="font-mono text-[11px] text-muted-foreground w-[200px] shrink-0 leading-5">
                      {scope.key}
                    </span>
                    <span className="text-[12px] leading-5 flex-1">
                      {t(`scope_descriptions.${scope.key}`)}
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
