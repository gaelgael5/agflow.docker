import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { adminBackupRemotesApi } from "@/lib/adminBackupRemotesApi";
import {
  OAuthAbortedError,
  OAuthError,
  PopupBlockedError,
  runGDriveOAuthFlow,
} from "@/lib/gdriveOAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Phase = "setup" | "auth" | "confirmed";

interface Props {
  onCompleted: (info: { connectionId: string; userEmail: string; folderId: string }) => void;
  onCancel: () => void;
}

export function GDriveFields({ onCompleted, onCancel }: Props) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("setup");
  const [name, setName] = useState("");
  const [folderName, setFolderName] = useState("agflow-backups");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [confirmation, setConfirmation] = useState<{ userEmail: string; folderId: string } | null>(
    null,
  );

  useEffect(() => {
    adminBackupRemotesApi
      .fetchGDriveRedirectUri()
      .then((r) => setRedirectUri(r.redirect_uri))
      .catch(() => {
        /* affichage retardé, non bloquant */
      });
  }, []);

  const handleAuthorize = async () => {
    if (!name || !folderName || !clientId || !clientSecret) {
      toast.error(t("backups.gdrive.errorRequired"));
      return;
    }
    setPhase("auth");
    try {
      const { state, authorize_url } = await adminBackupRemotesApi.startGDriveOAuth({
        name,
        folder_name: folderName,
        client_id: clientId,
        client_secret: clientSecret,
      });
      const info = await runGDriveOAuthFlow({ authorizeUrl: authorize_url, state });
      if (info.connection_id && info.user_email && info.folder_id) {
        setConfirmation({ userEmail: info.user_email, folderId: info.folder_id });
        setPhase("confirmed");
        onCompleted({
          connectionId: info.connection_id,
          userEmail: info.user_email,
          folderId: info.folder_id,
        });
      } else {
        toast.error(t("backups.gdrive.errorGeneric"));
        setPhase("setup");
      }
    } catch (err) {
      if (err instanceof PopupBlockedError) toast.error(t("backups.gdrive.errorPopupBlocked"));
      else if (err instanceof OAuthAbortedError) toast.error(t("backups.gdrive.errorAborted"));
      else if (err instanceof OAuthError)
        toast.error(t("backups.gdrive.errorOauth", { msg: err.message }));
      else toast.error(t("backups.gdrive.errorGeneric"));
      setPhase("setup");
    }
  };

  if (phase === "auth") {
    return (
      <div className="space-y-3">
        <p className="text-sm">{t("backups.gdrive.phaseAuthInProgress")}</p>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
      </div>
    );
  }

  if (phase === "confirmed" && confirmation) {
    return (
      <div className="space-y-3">
        <p className="font-medium">{t("backups.gdrive.phaseConfirmedTitle")}</p>
        <div className="text-sm text-muted-foreground">
          <div>
            {t("backups.gdrive.confirmedUserEmail")}:{" "}
            <strong>{confirmation.userEmail}</strong>
          </div>
          <div>
            {t("backups.gdrive.confirmedFolderId")}:{" "}
            <code>{confirmation.folderId}</code>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("backups.gdrive.phaseSetupTitle")}</p>

      <div>
        <Label htmlFor="gdrive-name">{t("backups.gdrive.fieldName")}</Label>
        <Input
          id="gdrive-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="My Drive backups"
        />
      </div>

      <div>
        <Label htmlFor="gdrive-redirect-uri">{t("backups.gdrive.fieldRedirectUri")}</Label>
        <Input
          id="gdrive-redirect-uri"
          value={redirectUri}
          readOnly
          className="font-mono text-xs"
        />
        <p className="text-xs text-muted-foreground mt-1">
          {t("backups.gdrive.fieldRedirectUriHint")}
        </p>
      </div>

      <div>
        <Label htmlFor="gdrive-client-id">{t("backups.gdrive.fieldClientId")}</Label>
        <Input
          id="gdrive-client-id"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="123456789-abc.apps.googleusercontent.com"
        />
        <p className="text-xs text-muted-foreground mt-1">
          {t("backups.gdrive.fieldClientIdHint")}
        </p>
      </div>

      <div>
        <Label htmlFor="gdrive-client-secret">{t("backups.gdrive.fieldClientSecret")}</Label>
        <Input
          id="gdrive-client-secret"
          type="password"
          value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)}
          placeholder="GOCSPX-..."
          autoComplete="new-password"
        />
      </div>

      <div>
        <Label htmlFor="gdrive-folder-name">{t("backups.gdrive.fieldFolderName")}</Label>
        <Input
          id="gdrive-folder-name"
          value={folderName}
          onChange={(e) => setFolderName(e.target.value)}
        />
        <p className="text-xs text-muted-foreground mt-1">
          {t("backups.gdrive.fieldFolderNameHint")}
        </p>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button onClick={handleAuthorize}>{t("backups.gdrive.btnAuthorize")}</Button>
      </div>
    </div>
  );
}
