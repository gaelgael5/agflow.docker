import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { dockerfilesApi, type BuildSummary } from "@/lib/dockerfilesApi";

/**
 * Polls the backend for build status every 1.5s while status is running/pending.
 * Invalidates the dockerfile caches when the build completes.
 */
export function useBuild(dockerfileId: string, buildId: string | null) {
  const [build, setBuild] = useState<BuildSummary | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!buildId) {
      setBuild(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      if (!buildId) return;
      try {
        const b = await dockerfilesApi.getBuild(dockerfileId, buildId);
        if (cancelled) return;
        setBuild(b);
        if (b.status === "pending" || b.status === "running") {
          timer = setTimeout(poll, 1500);
        } else {
          qc.invalidateQueries({ queryKey: ["dockerfiles"] });
          qc.invalidateQueries({ queryKey: ["dockerfile", dockerfileId] });
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [dockerfileId, buildId, qc]);

  return build;
}
