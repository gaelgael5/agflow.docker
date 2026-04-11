import { Badge } from "./badge";
import { cn } from "@/lib/utils";

export type StatusLevel = "missing" | "stale" | "fresh";

interface Props {
  level: StatusLevel;
  label: string;
  className?: string;
}

const DOT_CLASS: Record<StatusLevel, string> = {
  missing: "bg-red-500",
  stale: "bg-amber-500",
  fresh: "bg-emerald-500",
};

const VARIANT: Record<StatusLevel, "destructive" | "warning" | "success"> = {
  missing: "destructive",
  stale: "warning",
  fresh: "success",
};

export function StatusDot({ level, label, className }: Props) {
  return (
    <Badge variant={VARIANT[level]} className={cn(className)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", DOT_CLASS[level])} />
      {label}
    </Badge>
  );
}
