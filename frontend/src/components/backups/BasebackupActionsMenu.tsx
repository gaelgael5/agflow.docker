import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type BasebackupSummary } from "@/lib/pitrApi";
import { usePitrBasebackups } from "@/hooks/usePitr";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface BasebackupActionsMenuProps {
  basebackup: BasebackupSummary;
}

export function BasebackupActionsMenu({ basebackup }: BasebackupActionsMenuProps) {
  const { t } = useTranslation();
  const { remove, push } = usePitrBasebackups();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const onConfirmDelete = () => {
    remove.mutate(basebackup.id);
    setConfirmOpen(false);
  };

  const onRepush = (remoteId: string) => {
    push.mutate({ basebackupId: basebackup.id, remoteId });
  };

  const failedPushes = basebackup.pushes.filter((p) => p.status === "failed");

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="ghost">
            ⋯
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => setConfirmOpen(true)}>
            {t("common.delete")}
          </DropdownMenuItem>
          {failedPushes.map((p) => (
            <DropdownMenuItem
              key={p.remote_connection_id}
              onClick={() => onRepush(p.remote_connection_id)}
            >
              {t("backups.pitr.basebackups.repushTo", { remote: p.remote_connection_name })}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("backups.pitr.basebackups.deleteConfirm")}</DialogTitle>
            <DialogDescription>
              {t("backups.pitr.basebackups.deleteConfirmDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="destructive" onClick={onConfirmDelete}>
              {t("common.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
