import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import { TimelineRow } from "@/components/timeline/TimelineRow";
import {
  sessionsApi,
  type AgentInstance,
  type SessionDetail,
} from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

function bulletForAgent(a: AgentInstance) {
  return a.status === "busy" ? ("live" as const) : ("default" as const);
}

function SessionBreadcrumb({
  session,
  sessionId,
}: {
  session: SessionDetail | undefined;
  sessionId: string | undefined;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-1 text-xs text-muted-foreground mb-3">
      <Link to="/sessions" className="hover:text-primary">
        {t("sessions.page_title")}
      </Link>
      {session?.project_id && (
        <>
          <span className="opacity-50">/</span>
          <Link
            to={`/projects/${session.project_id}`}
            className="text-primary hover:underline flex items-center gap-1"
          >
            <FolderKanban className="h-3 w-3" /> {session.project_id}
          </Link>
        </>
      )}
      <span className="opacity-50">/</span>
      <code className="font-mono">{sessionId?.slice(0, 8)}</code>
    </div>
  );
}

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const sQ = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => sessionsApi.get(id!),
    enabled: Boolean(id),
    refetchInterval: 5_000,
  });
  const aQ = useQuery({
    queryKey: ["sessions", id, "agents"],
    queryFn: () => sessionsApi.listAgents(id!),
    enabled: Boolean(id),
    refetchInterval: 5_000,
  });

  const hasProject = Boolean(sQ.data?.project_id);
  const agentCount = aQ.data?.length ?? 0;
  const subtitleExtra =
    agentCount === 1
      ? t("sessions.agents_count_one", { count: 1 })
      : t("sessions.agents_count_other", { count: agentCount });

  return (
    <PageShell>
      <SessionBreadcrumb session={sQ.data} sessionId={id} />
      <PageHeader
        title={sQ.data?.name ?? (id ? `Session ${id.slice(0, 8)}` : "Session")}
        subtitle={
          sQ.data ? (
            <span className="flex items-center gap-2 flex-wrap text-xs">
              <Badge
                variant={sQ.data.status === "active" ? "default" : "secondary"}
              >
                {t(`sessions.status_${sQ.data.status}`)}
              </Badge>
              <span className="text-muted-foreground">{subtitleExtra}</span>
              <span className="text-muted-foreground">
                · {t("sessions.expires_in", {
                  when: new Date(sQ.data.expires_at).toLocaleTimeString(),
                })}
              </span>
            </span>
          ) : undefined
        }
      />

      <div
        className={cn(
          "max-w-3xl mx-auto px-5 py-7 relative",
          hasProject && "bg-gradient-to-r from-primary/5 to-transparent rounded-lg",
        )}
      >
        <TimelineRail variant="gradient" />

        {aQ.isLoading ? (
          <div className="space-y-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-md" />
            ))}
          </div>
        ) : agentCount === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            {t("sessions.session_detail.no_agents")}
          </p>
        ) : (
          aQ.data?.map((a) => (
            <TimelineRow
              key={a.id}
              leftContent={
                <>
                  {t(`sessions.status_${a.status}`)}
                  <br />
                  <small className="opacity-70">
                    {new Date(a.created_at).toLocaleTimeString()}
                  </small>
                </>
              }
              bulletVariant={bulletForAgent(a)}
              onClick={() => navigate(`/sessions/${id}/agents/${a.id}`)}
              rightContent={
                <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <strong>{a.agent_id}</strong>
                    <Badge variant="default" className="h-5">
                      {t(`sessions.status_${a.status}`)}
                    </Badge>
                  </div>
                  {a.mission && (
                    <div className="text-xs text-muted-foreground mt-1">
                      mission: {a.mission}
                    </div>
                  )}
                </div>
              }
            />
          ))
        )}
      </div>
    </PageShell>
  );
}
