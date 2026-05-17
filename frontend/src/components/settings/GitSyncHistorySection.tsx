import { useTranslation } from "react-i18next";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useGitSyncCommits } from "@/hooks/useGitSync";
import { type GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

function isGithub(url: string): boolean {
  try {
    return new URL(url).hostname === "github.com";
  } catch {
    return false;
  }
}

function extractErrorMessage(err: unknown): string {
  const resp = (err as { response?: { data?: { detail?: unknown } } }).response;
  const detail = resp?.data?.detail;
  if (typeof detail === "string") return detail;
  const msg = (err as { message?: string }).message;
  return msg ?? "Unknown error";
}

export function GitSyncHistorySection({ config }: Props) {
  const { t } = useTranslation();
  const isGh = isGithub(config.repo_url);
  const { data: commits, refetch, isFetching, error } = useGitSyncCommits(
    30,
    isGh,
  );

  if (!isGh) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("settings.gitSync.history.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.history.unsupportedHost")}
            <a
              href={config.repo_url}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary hover:underline"
            >
              {config.repo_url}
            </a>
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">
          {t("settings.gitSync.history.title")}
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {t("settings.gitSync.history.refresh")}
        </Button>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">
            {t("settings.gitSync.history.loadError", {
              error: extractErrorMessage(error),
            })}
          </p>
        ) : isFetching && !commits ? (
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.history.loading")}
          </p>
        ) : !commits || commits.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.history.empty")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.gitSync.history.colSha")}</TableHead>
                <TableHead>{t("settings.gitSync.history.colAuthor")}</TableHead>
                <TableHead>{t("settings.gitSync.history.colMessage")}</TableHead>
                <TableHead>{t("settings.gitSync.history.colDate")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {commits.map((c) => (
                <TableRow
                  key={c.sha}
                  className="cursor-pointer"
                  onClick={() =>
                    window.open(c.html_url, "_blank", "noopener,noreferrer")
                  }
                  title={t("settings.gitSync.history.openOnGitHub")}
                >
                  <TableCell className="font-mono text-xs">
                    {c.short_sha}
                  </TableCell>
                  <TableCell className="text-xs">{c.author_name}</TableCell>
                  <TableCell className="text-xs max-w-md truncate">
                    {c.message.split("\n")[0]}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(c.authored_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
