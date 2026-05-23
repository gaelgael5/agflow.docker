// frontend/src/components/restore/RestoreTimelineItem.tsx
import type { JSX, ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface RestoreTimelineItemProps {
  step: number;
  title: string;
  status: "pending" | "active" | "done";
  children?: ReactNode;
}

export function RestoreTimelineItem({
  step,
  title,
  status,
  children,
}: RestoreTimelineItemProps): JSX.Element {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-bold shrink-0",
            status === "done" && "border-green-500 bg-green-500 text-white",
            status === "active" && "border-primary bg-primary text-primary-foreground",
            status === "pending" && "border-muted-foreground text-muted-foreground",
          )}
        >
          {status === "done" ? <Check className="h-4 w-4" /> : step}
        </div>
        <div className={cn("mt-2 w-0.5 flex-1 bg-border", status === "pending" && "bg-muted")} />
      </div>
      <div className="pb-8 flex-1 min-w-0">
        <h3
          className={cn(
            "mb-3 text-sm font-semibold",
            status === "pending" && "text-muted-foreground",
          )}
        >
          {title}
        </h3>
        {status !== "pending" && children}
      </div>
    </div>
  );
}
