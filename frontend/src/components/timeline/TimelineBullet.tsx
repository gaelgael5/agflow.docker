import { cn } from "@/lib/utils";

export type TimelineBulletVariant = "default" | "selected" | "live" | "muted";

interface Props {
  variant?: TimelineBulletVariant;
  size?: number;
  className?: string;
}

export function TimelineBullet({
  variant = "default",
  size = 10,
  className,
}: Props) {
  const effectiveSize = variant === "selected" ? size + 4 : size;
  return (
    <span
      data-timeline-bullet
      data-variant={variant}
      style={{ width: effectiveSize, height: effectiveSize }}
      className={cn(
        "relative inline-block rounded-full shrink-0 transition-all",
        variant === "default" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_10px_hsl(var(--primary))]",
        variant === "selected" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_0_2px_hsl(var(--primary)),0_0_18px_hsl(var(--primary))]",
        variant === "live" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_10px_hsl(var(--primary))] animate-pulse-dot before:content-[''] before:absolute before:top-1/2 before:left-1/2 before:w-full before:h-full before:border-2 before:border-primary before:rounded-full before:box-border before:animate-ring-expand before:pointer-events-none",
        variant === "muted" &&
          "bg-muted-foreground opacity-50 shadow-[0_0_0_3px_hsl(var(--background))]",
        className,
      )}
    />
  );
}
