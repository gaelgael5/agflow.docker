import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { EnvVarStatus as Status } from "@/lib/secretsApi";

interface Props {
  name: string;
  status: Status | undefined;
  /** When true, renders as a compact dot + name; otherwise a full pill badge. */
  compact?: boolean;
  className?: string;
}

const DOT_CLASS: Record<Status, string> = {
  missing: "bg-red-500",
  empty: "bg-amber-500",
  ok: "bg-emerald-500",
};

const VARIANT: Record<Status, "destructive" | "warning" | "success"> = {
  missing: "destructive",
  empty: "warning",
  ok: "success",
};

export function EnvVarStatus({ name, status, compact, className }: Props) {
  const { t } = useTranslation();
  const effective: Status = status ?? "missing";
  const title = `${name} — ${t(`status.${effective}`)}`;

  if (compact) {
    return (
      <span
        className={cn("inline-flex items-center gap-1.5 font-mono text-[12px]", className)}
        title={title}
      >
        <span className={cn("w-1.5 h-1.5 rounded-full", DOT_CLASS[effective])} />
        {name}
      </span>
    );
  }

  return (
    <Badge variant={VARIANT[effective]} className={className} title={title}>
      <span className={cn("w-1.5 h-1.5 rounded-full", DOT_CLASS[effective])} />
      <span className="font-mono">{name}</span>
    </Badge>
  );
}
