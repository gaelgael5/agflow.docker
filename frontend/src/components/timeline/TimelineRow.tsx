import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { TimelineBullet, type TimelineBulletVariant } from "./TimelineBullet";

interface Props {
  leftContent: ReactNode;
  bulletVariant?: TimelineBulletVariant;
  rightContent: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function TimelineRow({
  leftContent,
  bulletVariant = "default",
  rightContent,
  onClick,
  className,
}: Props) {
  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_36px_1fr] items-center mb-4",
        onClick && "cursor-pointer transition-transform hover:translate-x-0.5",
        className,
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
    >
      <div className="text-right pr-4 text-xs text-muted-foreground">
        {leftContent}
      </div>
      <div className="flex items-center justify-center relative z-[1]">
        <TimelineBullet variant={bulletVariant} />
      </div>
      <div className="pl-4">{rightContent}</div>
    </div>
  );
}
