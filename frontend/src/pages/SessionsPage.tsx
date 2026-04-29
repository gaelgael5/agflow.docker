import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineBullet } from "@/components/timeline/TimelineBullet";
import { sessionsApi, type SessionListItem } from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

function bulletVariantFor(s: SessionListItem) {
  if (s.status !== "active") return "muted" as const;
  if (s.agent_count > 0) return "live" as const;
  return "default" as const;
}

export function SessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");

  const q = useQuery({
    queryKey: ["sessions", "list"],
    queryFn: () => sessionsApi.list(),
    refetchInterval: 5_000,
  });

  const grouped = useMemo(() => {
    const list = q.data ?? [];
    const fl = filter.trim().toLowerCase();
    const filtered = fl
      ? list.filter(
          (s) =>
            (s.name?.toLowerCase().includes(fl) ?? false) ||
            (s.project_id?.toLowerCase().includes(fl) ?? false) ||
            s.id.toLowerCase().includes(fl),
        )
      : list;
    const adHoc = filtered.filter((s) => !s.project_id);
    const byProject = new Map<string, SessionListItem[]>();
    for (const s of filtered) {
      if (!s.project_id) continue;
      const arr = byProject.get(s.project_id) ?? [];
      arr.push(s);
      byProject.set(s.project_id, arr);
    }
    return { adHoc, byProject };
  }, [q.data, filter]);

  return (
    <PageShell>
      <PageHeader
        title={t("sessions.page_title")}
        subtitle={t("sessions.subtitle")}
      />

      <div className="max-w-4xl mx-auto space-y-2">
        <Input
          placeholder={t("sessions.search_placeholder")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="max-w-sm"
        />

        {q.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14 w-full rounded-md" />
            ))}
          </div>
        ) : q.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("sessions.empty")}
          </p>
        ) : (
          <>
            {grouped.adHoc.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                onOpen={() => navigate(`/sessions/${s.id}`)}
              />
            ))}

            {[...grouped.byProject.entries()].map(([pid, items]) => (
              <div
                key={pid}
                className="border-l-2 border-dashed border-primary/30 bg-gradient-to-r from-primary/5 to-transparent rounded-r-lg px-4 py-2 my-3"
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-primary mb-2">
                  <FolderKanban className="h-4 w-4" />
                  <span>{pid}</span>
                  <span className="text-muted-foreground font-normal text-xs">
                    · {items.length} sessions
                  </span>
                </div>
                {items.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    onOpen={() => navigate(`/sessions/${s.id}`)}
                  />
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </PageShell>
  );
}

function SessionRow({
  session,
  onOpen,
}: {
  session: SessionListItem;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "grid grid-cols-[20px_2fr_1fr_1fr_1fr] gap-3 items-center",
        "rounded-md px-3 py-2 cursor-pointer transition-colors",
        "hover:bg-primary/5",
      )}
    >
      <TimelineBullet variant={bulletVariantFor(session)} />
      <div className="min-w-0">
        <div className="font-medium truncate">
          {session.name ?? session.id.slice(0, 12)}
        </div>
        <div className="text-xs text-muted-foreground truncate">
          {session.project_id
            ? t("sessions.project_label")
            : t("sessions.ad_hoc_label")}
          {" · "}
          <code className="font-mono">{session.id.slice(0, 8)}</code>
        </div>
      </div>
      <span className="text-sm">
        {session.agent_count === 1
          ? t("sessions.agents_count_one", { count: 1 })
          : t("sessions.agents_count_other", { count: session.agent_count })}
      </span>
      <Badge
        variant={session.status === "active" ? "default" : "secondary"}
        className="w-fit"
      >
        {t(`sessions.status_${session.status}`)}
      </Badge>
      <span className="text-xs text-muted-foreground">
        {new Date(session.created_at).toLocaleString()}
      </span>
    </div>
  );
}
