import { cn } from "@/lib/utils";

interface Props {
  variant?: "gradient" | "solid";
  className?: string;
}

export function TimelineRail({ variant = "gradient", className }: Props) {
  return (
    <div
      aria-hidden
      className={cn(
        "absolute top-8 bottom-8 left-1/2 -translate-x-px w-0.5 rounded-full",
        variant === "gradient" &&
          "bg-gradient-to-b from-primary/40 to-transparent",
        variant === "solid" && "bg-primary/40",
        className,
      )}
    />
  );
}
