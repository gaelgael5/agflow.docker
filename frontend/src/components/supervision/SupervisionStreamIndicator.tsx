import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { StreamStatus } from "@/hooks/useSupervisionStream";

interface Props {
  status: StreamStatus;
}

const DOT_CLASS: Record<StreamStatus, string> = {
  open: "bg-emerald-500",
  connecting: "bg-amber-500 animate-pulse",
  closed: "bg-muted-foreground",
};

const LABEL_KEY: Record<StreamStatus, string> = {
  open: "supervision.ws.connected",
  connecting: "supervision.ws.reconnecting",
  closed: "supervision.ws.disconnected",
};

export function SupervisionStreamIndicator({ status }: Props) {
  const { t } = useTranslation();
  const label = t(LABEL_KEY[status]);
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      title={label}
      data-stream-state={status}
      aria-label={label}
    >
      <span className={cn("w-2 h-2 rounded-full", DOT_CLASS[status])} aria-hidden />
      <span>{label}</span>
    </span>
  );
}
