import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { discoveryApi, type TargetSummary } from "@/lib/catalogsApi";

interface Props {
  serviceId: string;
  currentTargetName?: string;
  onSelect: (target: TargetSummary) => void;
  onClose: () => void;
}

export function TargetSelectorDialog({
  serviceId,
  currentTargetName,
  onSelect,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const [targets, setTargets] = useState<TargetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    discoveryApi
      .fetchTargets(serviceId)
      .then(setTargets)
      .finally(() => setLoading(false));
  }, [serviceId]);

  const filtered = filter
    ? targets.filter((t) =>
        t.name.toLowerCase().includes(filter.toLowerCase()),
      )
    : targets;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl sm:max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("target.dialog_title")}</DialogTitle>
          <DialogDescription>
            {t("target.dialog_subtitle")}
          </DialogDescription>
        </DialogHeader>

        <input
          autoFocus
          className="w-full bg-transparent text-sm border rounded px-3 py-1.5 outline-none placeholder:text-muted-foreground"
          placeholder={t("common.search")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />

        <div className="flex-1 overflow-y-auto -mx-6 px-6">
          {loading ? (
            <div className="space-y-2 py-3">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="text-muted-foreground text-[13px] italic py-3">
              {t("common.no_results")}
            </p>
          ) : (
            <ul className="divide-y">
              {filtered.map((target) => {
                const isCurrent = target.name === currentTargetName;
                return (
                  <li
                    key={target.id}
                    className="flex items-center gap-3 py-3"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <strong className="text-[13px]">
                          {target.name}
                        </strong>
                        {target.modes.map((m) => (
                          <Badge
                            key={m.runtime}
                            variant="secondary"
                            className="text-[10px] font-mono"
                          >
                            {m.runtime}
                          </Badge>
                        ))}
                      </div>
                      {target.description && (
                        <div className="text-[12px] text-muted-foreground mt-0.5">
                          {target.description}
                        </div>
                      )}
                    </div>
                    {isCurrent ? (
                      <span className="text-green-500 text-xs flex items-center gap-1">
                        <Check className="w-3.5 h-3.5" />
                        {t("search_modal.added")}
                      </span>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          onSelect(target);
                          onClose();
                        }}
                      >
                        {t("common.confirm")}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            <X className="w-3.5 h-3.5" />
            {t("search_modal.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
