import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface RestoreConfirmDialogProps {
  open: boolean;
  filename: string;
  isLoading: boolean;
  onConfirm: (filename: string) => void;
  onCancel: () => void;
}

export function RestoreConfirmDialog({
  open,
  filename,
  isLoading,
  onConfirm,
  onCancel,
}: RestoreConfirmDialogProps) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");

  useEffect(() => {
    if (open) setTyped("");
  }, [open, filename]);

  const matches = typed === filename;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !isLoading) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-destructive">
            {t("backups.restore.dialog.title")}
          </DialogTitle>
          <DialogDescription className="font-semibold text-destructive">
            {t("backups.restore.dialog.warning")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p>{t("backups.restore.dialog.instructions", { filename })}</p>
          <div className="space-y-2">
            <Label htmlFor="restore-confirm-input">
              {t("backups.restore.dialog.filenameLabel")}
            </Label>
            <Input
              id="restore-confirm-input"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={filename}
              autoComplete="off"
              disabled={isLoading}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={() => onConfirm(filename)}
            disabled={!matches || isLoading}
          >
            {t("backups.restore.dialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
