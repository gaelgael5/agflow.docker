import { useTranslation } from "react-i18next";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useInstanceDetail } from "@/hooks/useSupervision";
import type { InstanceDetail } from "@/lib/supervisionApi";

interface Props {
  instanceId: string | null;
  onClose: () => void;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function MessageRow({ m }: { m: Record<string, unknown> }) {
  const dir = m.direction as string;
  const arrow = dir === "in" ? "→" : "←";
  const time =
    typeof m.created_at === "string"
      ? new Date(m.created_at).toLocaleTimeString()
      : "";
  return (
    <div className="flex items-start gap-2 text-xs font-mono">
      <span className="text-muted-foreground w-12 shrink-0">{time}</span>
      <span className="w-3 text-muted-foreground">{arrow}</span>
      <span className="w-20 text-muted-foreground truncate">
        {m.kind as string}
      </span>
      <span className="flex-1 truncate">{JSON.stringify(m.payload)}</span>
    </div>
  );
}

function DetailBody({ data }: { data: InstanceDetail }) {
  const { t } = useTranslation();
  return (
    <div className="px-6 py-4 space-y-5">
      <Section title={t("supervision.drawer.section.mission")}>
        {data.mission ? (
          <span>« {data.mission} »</span>
        ) : (
          <span className="text-muted-foreground">
            {t("supervision.table.no_mission")}
          </span>
        )}
      </Section>

      <Section title={t("supervision.drawer.section.container")}>
        <div className="flex items-center gap-2">
          <code className="text-xs">{data.last_container_name ?? "—"}</code>
          {data.container_status && (
            <Badge variant="outline" className="text-xs">
              {data.container_status}
            </Badge>
          )}
        </div>
      </Section>

      <Section title={t("supervision.drawer.section.labels")}>
        <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto">
          {JSON.stringify(data.labels, null, 2)}
        </pre>
      </Section>

      <Section title={t("supervision.drawer.section.mom")}>
        <div className="flex gap-4 text-xs">
          <span>
            {t("supervision.kpi.mom.pending")}:{" "}
            <strong>{data.mom_counts.pending}</strong>
          </span>
          <span>
            {t("supervision.kpi.mom.claimed")}:{" "}
            <strong>{data.mom_counts.claimed}</strong>
          </span>
          <span className={cn(data.mom_counts.failed > 0 && "text-destructive")}>
            {t("supervision.kpi.mom.failed")}:{" "}
            <strong>{data.mom_counts.failed}</strong>
          </span>
        </div>
      </Section>

      <Separator />

      <Section title={t("supervision.drawer.section.messages")}>
        {data.recent_messages.length === 0 ? (
          <span className="text-muted-foreground text-xs">—</span>
        ) : (
          <div className="space-y-1">
            {data.recent_messages.map((m, idx) => (
              <MessageRow key={(m.msg_id as string) ?? idx} m={m} />
            ))}
          </div>
        )}
      </Section>

      {data.error_message && (
        <Section title={t("supervision.drawer.section.error")}>
          <pre className="text-xs text-destructive whitespace-pre-wrap">
            {data.error_message}
          </pre>
        </Section>
      )}
    </div>
  );
}

export function SupervisionInstanceDrawer({ instanceId, onClose }: Props) {
  const { t } = useTranslation();
  const q = useInstanceDetail(instanceId);
  const open = !!instanceId;

  return (
    <Sheet open={open} onOpenChange={(o) => (!o ? onClose() : null)}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>
            {q.data?.agent_id ?? t("supervision.page_title")}
          </SheetTitle>
          <SheetDescription>
            {q.data?.session_id?.slice(0, 8) ?? ""}
          </SheetDescription>
        </SheetHeader>

        {q.isLoading && (
          <div className="p-6 space-y-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}

        {q.error && (
          <div role="alert" className="p-6 text-sm text-destructive">
            {t("supervision.drawer.not_found")}
          </div>
        )}

        {q.data && <DetailBody data={q.data} />}
      </SheetContent>
    </Sheet>
  );
}
