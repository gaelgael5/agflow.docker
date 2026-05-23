import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { restoreApi, type RestoreExecuteRequest } from "@/lib/restoreApi";

interface RestoreConfirmStepProps {
  request: RestoreExecuteRequest;
  selectedFileName: string;
  selectedFileSize: number | null;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function RestoreConfirmStep({
  request,
  selectedFileName,
  selectedFileSize,
}: RestoreConfirmStepProps): JSX.Element {
  const { t } = useTranslation();

  const startMutation = useMutation({
    mutationFn: () => restoreApi.startRestore(request),
  });

  const jobId = startMutation.data?.job_id ?? null;

  const { data: jobStatus } = useQuery({
    queryKey: ["restore-job", jobId],
    queryFn: () => restoreApi.getJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2000 : false,
  });

  const status = jobStatus?.status ?? null;

  return (
    <div className="space-y-5">
      <div className="rounded-md border p-4 space-y-2 text-sm bg-muted/30">
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_file")}</span>
          <span className="font-mono font-medium">{selectedFileName}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_size")}</span>
          <span>{formatBytes(selectedFileSize)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_type")}</span>
          <span className="uppercase">{request.connection_type}</span>
        </div>
      </div>

      {!jobId && (
        <p className="text-sm text-amber-600">
          {t("restore.confirm_warning")}
        </p>
      )}

      {!jobId && (
        <Button
          variant="destructive"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
        >
          {startMutation.isPending ? t("common.loading") : t("restore.btn_restore")}
        </Button>
      )}

      {jobId && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {status === "running" && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            {status === "done" && <CheckCircle2 className="h-4 w-4 text-green-500" />}
            {status === "failed" && <XCircle className="h-4 w-4 text-destructive" />}
            <span className="text-sm font-medium">
              {status === "running" && t("restore.status_running")}
              {status === "done" && t("restore.status_done")}
              {status === "failed" && t("restore.status_failed")}
            </span>
          </div>
          {jobStatus?.log && (
            <pre className="rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
              {jobStatus.log}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
