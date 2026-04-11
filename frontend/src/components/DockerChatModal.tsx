import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Bot, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { slugify } from "@/lib/slugify";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface GeneratedDockerfile {
  dockerfile: string;
  entrypoint_sh: string;
  run_cmd_md: string;
  reasoning: string;
}

interface Props {
  onClose: () => void;
  onAccept: (
    dockerfileId: string,
    displayName: string,
    files: GeneratedDockerfile,
  ) => Promise<void>;
}

export function DockerChatModal({ onClose, onAccept }: Props) {
  const { t } = useTranslation();
  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [result, setResult] = useState<GeneratedDockerfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    "dockerfile" | "entrypoint_sh" | "run_cmd_md"
  >("dockerfile");
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<GeneratedDockerfile>(
        "/admin/dockerfiles/chat-generate",
        { description },
      );
      setResult(res.data);
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response
        ?.status;
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      if (status === 412) {
        setError(t("dockerfiles.chat.error_no_key"));
      } else if (status === 502) {
        setError(t("dockerfiles.chat.error_llm", { detail: detail ?? "" }));
      } else {
        setError(detail ?? t("dockerfiles.chat.error_generic"));
      }
    } finally {
      setGenerating(false);
    }
  }

  async function handleAccept() {
    if (!result || !displayName || !slug) return;
    setAccepting(true);
    try {
      await onAccept(slug, displayName, result);
      onClose();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(detail ?? t("dockerfiles.chat.error_generic"));
    } finally {
      setAccepting(false);
    }
  }

  function updateDisplayName(v: string) {
    setDisplayName(v);
    if (!slugTouched) setSlug(slugify(v));
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bot className="w-4 h-4" />
            {t("dockerfiles.chat.title")}
          </DialogTitle>
          <DialogDescription>
            {t("dockerfiles.chat.subtitle")}
          </DialogDescription>
        </DialogHeader>

        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t("dockerfiles.chat.placeholder")}
          rows={4}
          disabled={generating}
        />

        <Button
          onClick={handleGenerate}
          disabled={generating || description.trim().length < 10}
          className="self-start"
        >
          <Sparkles className="w-4 h-4" />
          {generating
            ? t("dockerfiles.chat.generating")
            : t("dockerfiles.chat.generate_button")}
        </Button>

        {error && (
          <div
            role="alert"
            className="rounded-md bg-destructive/5 border border-destructive/30 text-destructive p-2.5 text-[12px]"
          >
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-3">
            {result.reasoning && (
              <div className="rounded-md bg-blue-50 dark:bg-blue-950/30 border border-blue-200/60 dark:border-blue-900/40 p-2.5 text-[12px] text-blue-900 dark:text-blue-200">
                <strong>{t("dockerfiles.chat.reasoning")}:</strong>{" "}
                {result.reasoning}
              </div>
            )}

            <div className="flex gap-1">
              {(["dockerfile", "entrypoint_sh", "run_cmd_md"] as const).map(
                (tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setActiveTab(tab)}
                    className={cn(
                      "px-2.5 py-1 text-[11px] font-mono border rounded",
                      activeTab === tab
                        ? "bg-primary/10 border-primary/30 text-primary"
                        : "hover:bg-secondary",
                    )}
                  >
                    {tab === "dockerfile"
                      ? "Dockerfile"
                      : tab === "entrypoint_sh"
                        ? "entrypoint.sh"
                        : "run.cmd.md"}
                  </button>
                ),
              )}
            </div>

            <pre className="bg-zinc-900 text-zinc-100 rounded-md p-3 text-[11px] font-mono whitespace-pre-wrap max-h-64 overflow-auto">
              {result[activeTab]}
            </pre>

            <Card className="p-3">
              <div className="text-[12px] font-semibold mb-2">
                {t("dockerfiles.chat.accept_header")}
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
                  <Label className="text-[11px]">
                    {t("dockerfiles.new_dockerfile_name_prompt")}
                  </Label>
                  <Input
                    value={displayName}
                    onChange={(e) => updateDisplayName(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label className="text-[11px]">
                    {t("dockerfiles.new_dockerfile_id_prompt")}
                  </Label>
                  <Input
                    value={slug}
                    onChange={(e) => {
                      setSlugTouched(true);
                      setSlug(e.target.value);
                    }}
                    className="w-44 font-mono text-[12px]"
                  />
                </div>
                <Button
                  onClick={handleAccept}
                  disabled={accepting || !displayName.trim() || !slug.trim()}
                >
                  {accepting
                    ? t("dockerfiles.chat.creating")
                    : t("dockerfiles.chat.accept_button")}
                </Button>
              </div>
            </Card>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("agent_editor.cancel")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
