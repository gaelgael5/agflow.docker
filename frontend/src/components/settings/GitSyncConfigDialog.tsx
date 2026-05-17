import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { GitSyncAuthSection } from "./GitSyncAuthSection";
import { GitSyncTablesPicker } from "./GitSyncTablesPicker";
import { GitSyncCronSection } from "./GitSyncCronSection";
import { useAvailableTables, useUpsertConfig } from "@/hooks/useGitSync";
import {
  type GitSyncConfig,
  type GitSyncConfigUpsert,
} from "@/lib/gitSyncApi";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: GitSyncConfig | null;
};

function buildInitial(initial: GitSyncConfig | null): GitSyncConfigUpsert {
  return {
    repo_url: initial?.repo_url ?? "",
    auth_mode: initial?.auth_mode ?? "pat_https",
    auth_secret_ref: initial?.auth_secret_ref ?? "",
    branch: initial?.branch ?? "main",
    commit_author_name: initial?.commit_author_name ?? "agflow bot",
    commit_author_email: initial?.commit_author_email ?? "bot@agflow.local",
    excluded_columns: initial?.excluded_columns ?? {},
    selected_tables: initial?.selected_tables ?? [],
    cron_expr: initial?.cron_expr ?? null,
    cron_enabled: initial?.cron_enabled ?? false,
  };
}

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

function parseExcludedColumns(raw: string): Record<string, string[]> | null {
  try {
    const obj = JSON.parse(raw || "{}") as unknown;
    if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
      return null;
    }
    for (const [, val] of Object.entries(obj)) {
      if (!Array.isArray(val) || val.some((v) => typeof v !== "string")) {
        return null;
      }
    }
    return obj as Record<string, string[]>;
  } catch {
    return null;
  }
}

export function GitSyncConfigDialog({ open, onOpenChange, initial }: Props) {
  const { t } = useTranslation();
  const upsert = useUpsertConfig();
  const { data: availableTables = [] } = useAvailableTables();

  const [form, setForm] = useState<GitSyncConfigUpsert>(() =>
    buildInitial(initial),
  );
  const [excludedJson, setExcludedJson] = useState<string>(
    JSON.stringify(initial?.excluded_columns ?? {}, null, 2),
  );
  const [excludedError, setExcludedError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setForm(buildInitial(initial));
      setExcludedJson(JSON.stringify(initial?.excluded_columns ?? {}, null, 2));
      setExcludedError(null);
    }
  }, [open, initial]);

  const handleSave = async () => {
    const parsed = parseExcludedColumns(excludedJson);
    if (parsed === null) {
      setExcludedError(t("settings.gitSync.config.excludedColumnsInvalid"));
      return;
    }
    setExcludedError(null);
    try {
      await upsert.mutateAsync({ ...form, excluded_columns: parsed });
      toast.success(t("settings.gitSync.toast.configSaved"));
      onOpenChange(false);
    } catch (e) {
      toast.error(extractErrorMessage(e));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {initial
              ? t("settings.gitSync.config.editTitle")
              : t("settings.gitSync.config.createTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1">
            <Label htmlFor="repo_url">
              {t("settings.gitSync.config.repoUrl")}
            </Label>
            <Input
              id="repo_url"
              value={form.repo_url}
              onChange={(e) => setForm({ ...form, repo_url: e.target.value })}
              placeholder="https://github.com/org/repo"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="branch">
              {t("settings.gitSync.config.branch")}
            </Label>
            <Input
              id="branch"
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
            />
          </div>

          <GitSyncAuthSection
            authMode={form.auth_mode}
            authSecretRef={form.auth_secret_ref}
            onChangeAuthMode={(mode) => setForm({ ...form, auth_mode: mode })}
            onChangeAuthSecretRef={(ref) =>
              setForm({ ...form, auth_secret_ref: ref })
            }
          />

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="commit_author_name">
                {t("settings.gitSync.config.commitAuthorName")}
              </Label>
              <Input
                id="commit_author_name"
                value={form.commit_author_name}
                onChange={(e) =>
                  setForm({ ...form, commit_author_name: e.target.value })
                }
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="commit_author_email">
                {t("settings.gitSync.config.commitAuthorEmail")}
              </Label>
              <Input
                id="commit_author_email"
                type="email"
                value={form.commit_author_email}
                onChange={(e) =>
                  setForm({ ...form, commit_author_email: e.target.value })
                }
              />
            </div>
          </div>

          <GitSyncTablesPicker
            selected={form.selected_tables}
            available={availableTables}
            onChange={(next) => setForm({ ...form, selected_tables: next })}
          />

          <div className="space-y-1">
            <Label htmlFor="excluded_columns">
              {t("settings.gitSync.config.excludedColumns")}
            </Label>
            <Textarea
              id="excluded_columns"
              value={excludedJson}
              onChange={(e) => setExcludedJson(e.target.value)}
              rows={5}
              className="font-mono text-[12px]"
            />
            <p className="text-[11px] text-muted-foreground">
              {t("settings.gitSync.config.excludedColumnsHint")}
            </p>
            {excludedError && (
              <p className="text-[12px] text-destructive" role="alert">
                {excludedError}
              </p>
            )}
          </div>

          <GitSyncCronSection
            enabled={form.cron_enabled}
            expr={form.cron_expr}
            onChangeEnabled={(enabled) =>
              setForm({ ...form, cron_enabled: enabled })
            }
            onChangeExpr={(expr) => setForm({ ...form, cron_expr: expr })}
          />
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={upsert.isPending}
          >
            {t("settings.gitSync.config.cancel")}
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={upsert.isPending || form.selected_tables.length === 0}
          >
            {t("settings.gitSync.config.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
