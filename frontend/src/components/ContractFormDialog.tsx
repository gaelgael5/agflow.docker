import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { contractsApi, type ContractCreatePayload } from "@/lib/contractsApi";

interface Props {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (payload: ContractCreatePayload) => Promise<void>;
}

interface DetectedTag {
  name: string;
  operation_count: number;
}

export function ContractFormDialog({ agentId, open, onOpenChange, onSave }: Props) {
  const { t } = useTranslation();
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [specContent, setSpecContent] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("Authorization");
  const [authPrefix, setAuthPrefix] = useState("Bearer");
  const [authSecretRef, setAuthSecretRef] = useState("");
  const [outputDir, setOutputDir] = useState("workspace/docs/ctr");
  const [detectedTags, setDetectedTags] = useState<DetectedTag[]>([]);
  const [fetching, setFetching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFetch() {
    if (!sourceUrl) return;
    setFetching(true);
    setError(null);
    try {
      const { content } = await contractsApi.fetchSpec(agentId, sourceUrl);
      setSpecContent(content);
      parseSpec(content);
    } catch {
      setError(t("contracts.fetch_error"));
    } finally {
      setFetching(false);
    }
  }

  function parseSpec(content: string) {
    try {
      const spec = JSON.parse(content);
      const paths = spec.paths || {};
      const tagOps: Record<string, number> = {};
      for (const [, methods] of Object.entries(paths)) {
        for (const [method, operation] of Object.entries(methods as Record<string, unknown>)) {
          if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
          const op = operation as { tags?: string[] };
          for (const tag of op.tags || ["untagged"]) {
            tagOps[tag] = (tagOps[tag] || 0) + 1;
          }
        }
      }
      setDetectedTags(
        Object.entries(tagOps)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([name, count]) => ({ name, operation_count: count }))
      );
      // Auto-detect base_url from servers
      const servers = spec.servers || [];
      if (servers[0]?.url && !baseUrl) {
        setBaseUrl(servers[0].url);
      }
    } catch {
      setDetectedTags([]);
    }
  }

  async function handleSave() {
    if (!slug || !specContent) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        slug,
        display_name: displayName || slug,
        description,
        source_type: sourceUrl ? "url" : "manual",
        source_url: sourceUrl || undefined,
        spec_content: specContent,
        base_url: baseUrl,
        auth_header: authHeader,
        auth_prefix: authPrefix,
        auth_secret_ref: authSecretRef || undefined,
        output_dir: outputDir,
      });
      // Reset form
      setSlug("");
      setDisplayName("");
      setDescription("");
      setSourceUrl("");
      setSpecContent("");
      setBaseUrl("");
      setAuthSecretRef("");
      setDetectedTags([]);
      onOpenChange(false);
    } catch {
      setError(t("contracts.parse_error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl sm:max-h-[85vh] flex flex-col overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("contracts.dialog_title_new")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px]">{t("contracts.slug")}</Label>
              <Input value={slug} onChange={(e) => setSlug(e.target.value)} className="mt-1 font-mono text-[12px]" />
            </div>
            <div>
              <Label className="text-[11px]">{t("contracts.display_name")}</Label>
              <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1 text-[12px]" />
            </div>
          </div>

          <div>
            <Label className="text-[11px]">{t("contracts.description")}</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1 text-[12px]" />
          </div>

          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label className="text-[11px]">{t("contracts.source_url")}</Label>
              <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} className="mt-1 text-[12px] font-mono" placeholder="https://..." />
            </div>
            <Button size="sm" onClick={handleFetch} disabled={fetching || !sourceUrl}>
              {fetching ? "..." : t("contracts.fetch_button")}
            </Button>
          </div>

          <div>
            <Label className="text-[11px]">{t("contracts.spec_content")}</Label>
            <Textarea
              value={specContent}
              onChange={(e) => { setSpecContent(e.target.value); parseSpec(e.target.value); }}
              rows={6}
              className="mt-1 font-mono text-[11px]"
              placeholder='{"openapi": "3.0.0", ...}'
            />
          </div>

          {detectedTags.length > 0 && (
            <div>
              <Label className="text-[11px]">{t("contracts.tags_detected")}</Label>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {detectedTags.map((tag) => (
                  <Badge key={tag.name} variant="secondary" className="text-[10px]">
                    {tag.name} ({tag.operation_count})
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px]">{t("contracts.base_url")}</Label>
              <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="mt-1 font-mono text-[12px]" placeholder="${AGFLOW_API_URL}" />
            </div>
            <div>
              <Label className="text-[11px]">{t("contracts.auth_secret_ref")}</Label>
              <Input value={authSecretRef} onChange={(e) => setAuthSecretRef(e.target.value)} className="mt-1 font-mono text-[12px]" placeholder="${AGFLOW_TOKEN}" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[11px]">{t("contracts.auth_header")}</Label>
              <Input value={authHeader} onChange={(e) => setAuthHeader(e.target.value)} className="mt-1 text-[12px]" />
            </div>
            <div>
              <Label className="text-[11px]">{t("contracts.auth_prefix")}</Label>
              <Input value={authPrefix} onChange={(e) => setAuthPrefix(e.target.value)} className="mt-1 text-[12px]" />
            </div>
          </div>

          <div>
            <Label className="text-[11px]">Répertoire de sortie</Label>
            <Input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} className="mt-1 font-mono text-[12px]" placeholder="workspace/docs/ctr" />
          </div>

          {error && <p className="text-destructive text-[12px]">{error}</p>}
        </div>

        <DialogFooter className="mt-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSave} disabled={saving || !slug || !specContent}>
            {saving ? "..." : t("contracts.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
