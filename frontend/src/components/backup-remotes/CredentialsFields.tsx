import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Kind } from "./types";

interface CredentialsFieldsProps {
  kind: Kind;
  username: string;
  password: string;
  hasExisting: boolean;
  onChangeUsername: (v: string) => void;
  onChangePassword: (v: string) => void;
  vaultHint?: string;
}

export function CredentialsFields({
  kind,
  username,
  password,
  hasExisting,
  onChangeUsername,
  onChangePassword,
  vaultHint,
}: CredentialsFieldsProps) {
  const { t } = useTranslation();
  const placeholder = hasExisting ? "••••••••" : "";

  return (
    <>
      <div
        className={`rounded-md border px-3 py-2 text-sm ${
          hasExisting
            ? "border-border bg-muted/50 text-foreground"
            : "border-destructive/50 bg-destructive/10 text-destructive"
        }`}
      >
        {hasExisting
          ? t("backup_remotes.credentials_ok")
          : t("backup_remotes.credentials_missing")}
      </div>

      <div>
        <Label>
          {kind === "s3"
            ? t("backup_remotes.access_key_id")
            : t("backup_remotes.username")}
        </Label>
        <Input
          placeholder={placeholder}
          value={username}
          onChange={(e) => onChangeUsername(e.target.value)}
        />
      </div>

      <div>
        <Label>
          {kind === "s3"
            ? t("backup_remotes.secret_access_key")
            : t("backup_remotes.password")}
        </Label>
        <Input
          type="password"
          placeholder={placeholder}
          value={password}
          onChange={(e) => onChangePassword(e.target.value)}
        />
        {vaultHint && (
          <p className="mt-1 text-[10px] text-muted-foreground font-mono">{vaultHint}</p>
        )}
      </div>
    </>
  );
}
