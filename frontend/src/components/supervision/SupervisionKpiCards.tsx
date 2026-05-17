import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { SupervisionOverview } from "@/lib/supervisionApi";
import { FolderKanban, Bot, Container, Mailbox } from "lucide-react";

interface Props {
  data: SupervisionOverview | undefined;
}

interface Row {
  label: string;
  value: number | string;
  tone?: "default" | "primary" | "destructive" | "muted" | "success";
}

function Tone({
  tone,
  children,
}: {
  tone: Row["tone"];
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "tabular-nums font-semibold text-2xl",
        tone === "primary" && "text-primary",
        tone === "destructive" && "text-destructive",
        tone === "muted" && "text-muted-foreground",
        tone === "success" && "text-emerald-600 dark:text-emerald-400",
      )}
    >
      {children}
    </span>
  );
}

function KpiCard({
  title,
  icon: Icon,
  rows,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  rows: Row[];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between items-baseline">
            <span className="text-sm text-muted-foreground">{r.label}</span>
            <Tone tone={r.tone}>{r.value}</Tone>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SkeletonCard() {
  return (
    <div role="status" aria-busy="true" aria-live="polite">
      <Skeleton className="h-32 w-full rounded-md" />
    </div>
  );
}

export function SupervisionKpiCards({ data }: Props) {
  const { t } = useTranslation();

  if (!data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  const containersDisplay =
    data.containers_running === null ? "—" : data.containers_running;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      <KpiCard
        title={t("supervision.kpi.sessions.title")}
        icon={FolderKanban}
        rows={[
          {
            label: t("supervision.kpi.sessions.active"),
            value: data.sessions.active,
            tone: "success",
          },
          {
            label: t("supervision.kpi.sessions.closed"),
            value: data.sessions.closed,
            tone: "muted",
          },
          {
            label: t("supervision.kpi.sessions.expired"),
            value: data.sessions.expired,
            tone: data.sessions.expired > 0 ? "destructive" : "muted",
          },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.agents.title")}
        icon={Bot}
        rows={[
          {
            label: t("supervision.kpi.agents.idle"),
            value: data.agents.idle,
            tone: "default",
          },
          {
            label: t("supervision.kpi.agents.busy"),
            value: data.agents.busy,
            tone: data.agents.busy > 0 ? "primary" : "default",
          },
          {
            label: t("supervision.kpi.agents.error"),
            value: data.agents.error,
            tone: data.agents.error > 0 ? "destructive" : "muted",
          },
          {
            label: t("supervision.kpi.agents.destroyed"),
            value: data.agents.destroyed_total,
            tone: "muted",
          },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.containers.title")}
        icon={Container}
        rows={[
          {
            label: t("supervision.kpi.containers.running"),
            value: containersDisplay,
            tone: "default",
          },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.mom.title")}
        icon={Mailbox}
        rows={[
          {
            label: t("supervision.kpi.mom.pending"),
            value: data.mom.pending,
            tone: "default",
          },
          {
            label: t("supervision.kpi.mom.claimed"),
            value: data.mom.claimed,
            tone: data.mom.claimed > 0 ? "primary" : "default",
          },
          {
            label: t("supervision.kpi.mom.failed"),
            value: data.mom.failed,
            tone: data.mom.failed > 0 ? "destructive" : "muted",
          },
        ]}
      />
    </div>
  );
}
