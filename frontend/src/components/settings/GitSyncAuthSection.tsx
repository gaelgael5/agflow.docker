import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTestSecretRef } from "@/hooks/useGitSync";
import { type AuthMode } from "@/lib/gitSyncApi";

type Props = {
  authMode: AuthMode;
  authSecretRef: string;
  onChangeAuthMode: (mode: AuthMode) => void;
  onChangeAuthSecretRef: (ref: string) => void;
};

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

export function GitSyncAuthSection({
  authMode,
  authSecretRef,
  onChangeAuthMode,
  onChangeAuthSecretRef,
}: Props) {
  const { t } = useTranslation();
  const test = useTestSecretRef();

  const handleTestSecret = async () => {
    if (!authSecretRef) return;
    try {
      const result = await test.mutateAsync(authSecretRef);
      if (result.ok) {
        toast.success(t("settings.gitSync.toast.harpocrateOk"));
      } else {
        toast.error(
          t("settings.gitSync.toast.harpocrateFailed", {
            error: result.error ?? "?",
          }),
        );
      }
    } catch (e) {
      toast.error(
        t("settings.gitSync.toast.harpocrateFailed", {
          error: extractErrorMessage(e),
        }),
      );
    }
  };

  return (
    <>
      <div className="space-y-1">
        <Label htmlFor="auth_mode">
          {t("settings.gitSync.config.authMode")}
        </Label>
        <Select
          value={authMode}
          onValueChange={(v) => onChangeAuthMode(v as AuthMode)}
        >
          <SelectTrigger id="auth_mode">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ssh_key">
              {t("settings.gitSync.config.authMode_ssh_key")}
            </SelectItem>
            <SelectItem value="pat_https">
              {t("settings.gitSync.config.authMode_pat_https")}
            </SelectItem>
            <SelectItem value="basic_https">
              {t("settings.gitSync.config.authMode_basic_https")}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label htmlFor="auth_secret_ref">
          {t("settings.gitSync.config.authSecretRef")}
        </Label>
        <div className="flex gap-2">
          <Input
            id="auth_secret_ref"
            value={authSecretRef}
            onChange={(e) => onChangeAuthSecretRef(e.target.value)}
            placeholder="${vault://default:gitsync/pat}"
          />
          <Button
            type="button"
            variant="outline"
            onClick={handleTestSecret}
            disabled={!authSecretRef || test.isPending}
          >
            {t("settings.gitSync.config.testHarpocrate")}
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          {t("settings.gitSync.config.authSecretRefHint")}
        </p>
      </div>
    </>
  );
}
