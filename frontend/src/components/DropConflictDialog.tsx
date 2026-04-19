import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export type ConflictAction = "replace" | "rename" | "cancel";

export interface ConflictResolution {
  action: ConflictAction;
  applyToAll: boolean;
}

interface Props {
  open: boolean;
  name: string;
  section: string;
  suggestedRename: string;
  onResolve: (resolution: ConflictResolution) => void;
  onOpenChange: (open: boolean) => void;
}

export function DropConflictDialog({
  open,
  name,
  section,
  suggestedRename,
  onResolve,
  onOpenChange,
}: Props) {
  const { t } = useTranslation();
  const [applyToAll, setApplyToAll] = useState(false);

  const resolve = (action: ConflictAction) => {
    onResolve({ action, applyToAll });
    setApplyToAll(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("roles.drop.conflict_title")}</DialogTitle>
          <DialogDescription>
            {t("roles.drop.conflict_message", { name, section })}
          </DialogDescription>
        </DialogHeader>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={applyToAll}
            onChange={(e) => setApplyToAll(e.target.checked)}
          />
          {t("roles.drop.conflict_apply_all")}
        </label>

        <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={() => resolve("cancel")}>
            {t("roles.drop.conflict_cancel")}
          </Button>
          <Button variant="outline" onClick={() => resolve("rename")}>
            {t("roles.drop.conflict_rename", { suggested: suggestedRename })}
          </Button>
          <Button onClick={() => resolve("replace")}>
            {t("roles.drop.conflict_replace")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
