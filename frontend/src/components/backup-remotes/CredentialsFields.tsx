import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Kind } from "./types";

interface CredentialsFieldsProps {
  kind: Kind;
  username: string;
  password: string;
  privateKey: string;
  hasExisting: boolean;
  onChangeUsername: (v: string) => void;
  onChangePassword: (v: string) => void;
  onChangePrivateKey: (v: string) => void;
}

export function CredentialsFields({
  kind,
  username,
  password,
  privateKey,
  hasExisting,
  onChangeUsername,
  onChangePassword,
  onChangePrivateKey,
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

      {kind === "sftp" && (
        <div>
          <Label>{t("backup_remotes.private_key")}</Label>
          <Textarea
            className="font-mono text-xs"
            rows={4}
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
            value={privateKey}
            onChange={(e) => onChangePrivateKey(e.target.value)}
          />
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("backup_remotes.private_key_hint")}
          </p>
        </div>
      )}

      <div>
        <Label>
          {kind === "s3"
            ? t("backup_remotes.secret_access_key")
            : kind === "sftp"
              ? t("backup_remotes.password_or_passphrase")
              : t("backup_remotes.password")}
        </Label>
        <Input
          type="password"
          placeholder={placeholder}
          value={password}
          onChange={(e) => onChangePassword(e.target.value)}
        />
      </div>
    </>
  );
}
