import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import { TimelineRow } from "@/components/timeline/TimelineRow";
import { sessionsApi, type MomMessage } from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

const BADGE_BY_KIND: Record<string, string> = {
  llm_call: "bg-emerald-500/20 text-emerald-500 border border-emerald-500/30",
  tool_call: "bg-blue-500/20 text-blue-500 border border-blue-500/30",
  mcp_call: "bg-purple-500/20 text-purple-500 border border-purple-500/30",
  file_change: "bg-amber-500/20 text-amber-500 border border-amber-500/30",
  error: "bg-red-500/20 text-red-500 border border-red-500/30",
  instruction: "bg-indigo-500/20 text-indigo-500 border border-indigo-500/30",
  event: "bg-slate-500/20 text-slate-500 border border-slate-500/30",
};

function summarize(m: MomMessage): string {
  const p = (m.payload ?? {}) as Record<string, unknown>;
  if (typeof p.prompt === "string") return p.prompt;
  if (typeof p.tool === "string") return p.tool;
  if (typeof p.message === "string") return p.message;
  if (typeof p.text === "string") return p.text;
  try {
    return JSON.stringify(p).slice(0, 80);
  } catch {
    return "";
  }
}

export function SessionAgentTimelinePage() {
  const { id, instanceId } = useParams<{ id: string; instanceId: string }>();
  const { t } = useTranslation();
  const [filter, setFilter] = useState("");

  const sQ = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => sessionsApi.get(id!),
    enabled: Boolean(id),
  });
  const aQ = useQuery({
    queryKey: ["sessions", id, "agents"],
    queryFn: () => sessionsApi.listAgents(id!),
    enabled: Boolean(id),
  });
  const mQ = useQuery({
    queryKey: ["sessions", id, "agents", instanceId, "messages"],
    queryFn: () => sessionsApi.listMessages(id!, instanceId!, { limit: 200 }),
    enabled: Boolean(id && instanceId),
    refetchInterval: 5_000,
  });

  const agent = aQ.data?.find((a) => a.id === instanceId);
  const messages = useMemo(() => {
    const data = mQ.data ?? [];
    const fl = filter.trim().toLowerCase();
    return fl
      ? data.filter(
          (m) =>
            m.kind.toLowerCase().includes(fl) ||
            summarize(m).toLowerCase().includes(fl),
        )
      : data;
  }, [mQ.data, filter]);

  const lastIndex = messages.length - 1;

  return (
    <PageShell>
      <div className="flex items-center gap-1 text-xs text-muted-foreground mb-3">
        <Link to="/sessions" className="hover:text-primary">
          {t("sessions.page_title")}
        </Link>
        {sQ.data?.project_id && (
          <>
            <span className="opacity-50">/</span>
            <Link
              to={`/projects/${sQ.data.project_id}`}
              className="text-primary flex items-center gap-1"
            >
              <FolderKanban className="h-3 w-3" /> {sQ.data.project_id}
            </Link>
          </>
        )}
        <span className="opacity-50">/</span>
        <Link to={`/sessions/${id}`} className="hover:text-primary">
          <code className="font-mono">{id?.slice(0, 8)}</code>
        </Link>
        <span className="opacity-50">/</span>
        <span>{agent?.agent_id ?? "…"}</span>
      </div>

      <PageHeader
        title={agent?.agent_id ?? t("sessions.page_title")}
        subtitle={agent?.mission ?? undefined}
        actions={
          <div className="flex gap-2">
            <Input
              placeholder={t("sessions.agent_timeline.filter_placeholder")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-48"
            />
            <Badge variant="default">
              {t("sessions.agent_timeline.live_badge")}
            </Badge>
          </div>
        }
      />

      <div className="max-w-3xl mx-auto px-5 py-8 relative">
        <TimelineRail variant="solid" />

        {mQ.isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full rounded-md" />
            ))}
          </div>
        ) : messages.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            {t("sessions.agent_timeline.no_messages")}
          </p>
        ) : (
          messages.map((m, idx) => {
            const isLast = idx === lastIndex;
            const isLiveTail = isLast && sQ.data?.status === "active";
            return (
              <TimelineRow
                key={m.msg_id}
                bulletVariant={isLiveTail ? "live" : "default"}
                leftContent={
                  <span className="font-mono">
                    {new Date(m.created_at).toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                }
                rightContent={
                  <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-[11px] px-2 py-0.5 rounded-full font-medium",
                          BADGE_BY_KIND[m.kind] ??
                            "bg-muted text-muted-foreground",
                        )}
                      >
                        {m.kind}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {m.direction === "in"
                          ? t("sessions.agent_timeline.direction_in")
                          : t("sessions.agent_timeline.direction_out")}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 truncate">
                      {summarize(m)}
                    </p>
                  </div>
                }
              />
            );
          })
        )}
      </div>
    </PageShell>
  );
}
