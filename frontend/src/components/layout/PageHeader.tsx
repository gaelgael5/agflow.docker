import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  /** Optional right-aligned action area (buttons, filters…). */
  actions?: ReactNode;
}

/**
 * Standard page header used at the top of every admin page. Provides
 * consistent typography, spacing and optional right-aligned actions.
 * Responsive: stacks vertically on small screens.
 */
export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="mb-6 md:mb-8 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <h1 className="text-[22px] md:text-[26px] font-semibold text-foreground tracking-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-muted-foreground mt-1 md:mt-1.5 text-[13px] md:text-[14px]">
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {actions}
        </div>
      )}
    </div>
  );
}

interface PageShellProps {
  children: ReactNode;
  /** max content width — defaults to 6xl (1152px). */
  maxWidth?: "4xl" | "5xl" | "6xl" | "full";
}

/**
 * Standard padded container for admin pages. Use around the entire page
 * content (after the AppLayout main).
 */
export function PageShell({ children, maxWidth = "6xl" }: PageShellProps) {
  const maxClass =
    maxWidth === "full"
      ? ""
      : maxWidth === "4xl"
        ? "max-w-4xl"
        : maxWidth === "5xl"
          ? "max-w-5xl"
          : "max-w-6xl";
  return (
    <div className={`px-4 md:px-8 py-6 md:py-10 ${maxClass}`}>{children}</div>
  );
}
