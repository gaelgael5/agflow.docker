import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Pencil, KeyRound, Copy, Check } from "lucide-react";
import { useApiKeys } from "@/hooks/useApiKeys";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogDescription,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ApiKeySummary, ApiKeyCreated, ApiKeyCreate, ApiKeyUpdate } from "@/lib/apiKeysApi";
import { ScopesEditor } from "@/components/ScopesEditor";

// ─── Create Dialog ────────────────────────────────────────────────────────────

interface CreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (payload: ApiKeyCreate) => Promise<void>;
}

function CreateDialog({ open, onOpenChange, onCreate }: CreateDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [rateLimit, setRateLimit] = useState("120");
  const [expiresIn, setExpiresIn] = useState<string>("never");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setName("");
    setChecked(new Set());
    setRateLimit("120");
    setExpiresIn("never");
    setError(null);
  }

  function handleOpenChange(val: boolean) {
    if (!val) reset();
    onOpenChange(val);
  }

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const payload: ApiKeyCreate = {
        name,
        scopes: [...checked],
        rate_limit: parseInt(rateLimit, 10) || 120,
        expires_in: expiresIn,
      };
      await onCreate(payload);
      handleOpenChange(false);
    } catch (e) {
      const raw = (e as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      const detail =
        typeof raw === "string"
          ? raw
          : Array.isArray(raw)
            ? raw.map((d: { msg?: string }) => d.msg ?? "").join(", ")
            : typeof raw === "object" && raw !== null
              ? JSON.stringify(raw)
              : t("api_keys.create_dialog_title");
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("api_keys.create_dialog_title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("api_keys.create_dialog_title")}
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 space-y-4 pr-1">
          <div className="space-y-1.5">
            <Label htmlFor="key-name">{t("api_keys.field_name")}</Label>
            <Input
              id="key-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. ci-bot"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="key-rate-limit">{t("api_keys.field_rate_limit")}</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="key-rate-limit"
                  type="number"
                  min={1}
                  value={rateLimit}
                  onChange={(e) => setRateLimit(e.target.value)}
                  className="w-24"
                />
                <span className="text-sm text-muted-foreground">{t("api_keys.rate_unit")}</span>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>{t("api_keys.field_expiration")}</Label>
              <Select value={expiresIn} onValueChange={setExpiresIn}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="3m">{t("api_keys.expire_3m")}</SelectItem>
                  <SelectItem value="6m">{t("api_keys.expire_6m")}</SelectItem>
                  <SelectItem value="9m">{t("api_keys.expire_9m")}</SelectItem>
                  <SelectItem value="12m">{t("api_keys.expire_12m")}</SelectItem>
                  <SelectItem value="never">{t("api_keys.expire_never")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>{t("api_keys.field_scopes")}</Label>
            <ScopesEditor
              selected={[...checked]}
              onChange={(scopes) => setChecked(new Set(scopes))}
            />
          </div>

          {error && (
            <p className="text-[12px] text-destructive" role="alert">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={submitting || !name}>
            {t("common.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Token Reveal Dialog ──────────────────────────────────────────────────────

interface TokenRevealDialogProps {
  created: ApiKeyCreated | null;
  onClose: () => void;
}

function TokenRevealDialog({ created, onClose }: TokenRevealDialogProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const token = created?.full_key ?? "";
    try {
      await navigator.clipboard.writeText(token);
    } catch {
      // fallback: select the input
      const input = document.getElementById("token-reveal-input") as HTMLInputElement | null;
      input?.select();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog open={!!created} onOpenChange={() => undefined}>
      <DialogContent className="max-w-lg" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{t("api_keys.token_created_title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("api_keys.token_warning")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-md bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3">
            <p className="text-sm text-amber-800 dark:text-amber-300 font-medium">
              {t("api_keys.token_warning")}
            </p>
          </div>

          <div className="flex gap-2">
            <Input
              id="token-reveal-input"
              readOnly
              value={created?.full_key ?? ""}
              className="font-mono text-xs"
            />
            <Button variant="outline" size="sm" onClick={handleCopy} className="shrink-0">
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 mr-1 text-green-600" />
                  {t("api_keys.token_copied")}
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 mr-1" />
                  {t("api_keys.token_copy")}
                </>
              )}
            </Button>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={onClose}>{t("api_keys.token_close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Edit Dialog ──────────────────────────────────────────────────────────────

interface EditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  apiKey: ApiKeySummary | null;
  onSave: (payload: ApiKeyUpdate) => Promise<void>;
}

function EditDialog({ open, onOpenChange, apiKey, onSave }: EditDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [rateLimit, setRateLimit] = useState("120");
  const [saving, setSaving] = useState(false);

  function handleOpenChange(val: boolean) {
    if (val && apiKey) {
      setName(apiKey.name);
      setChecked(new Set(apiKey.scopes));
      setRateLimit(String(apiKey.rate_limit ?? 120));
    }
    onOpenChange(val);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({
        name,
        scopes: [...checked],
        rate_limit: parseInt(rateLimit, 10) || 120,
      });
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("api_keys.edit_dialog_title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("api_keys.edit_dialog_title")}
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 space-y-4 pr-1">
          <div className="space-y-1.5">
            <Label htmlFor="edit-key-name">{t("api_keys.field_name")}</Label>
            <Input
              id="edit-key-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="edit-rate-limit">{t("api_keys.field_rate_limit")}</Label>
            <div className="flex items-center gap-2">
              <Input
                id="edit-rate-limit"
                type="number"
                min={1}
                value={rateLimit}
                onChange={(e) => setRateLimit(e.target.value)}
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">{t("api_keys.rate_unit")}</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>{t("api_keys.field_expiration")}</Label>
            <p className="text-xs text-muted-foreground">{t("api_keys.edit_expiry_hint")}</p>
          </div>

          <div className="space-y-1.5">
            <Label>{t("api_keys.field_scopes")}</Label>
            <ScopesEditor
              selected={[...checked]}
              onChange={(scopes) => setChecked(new Set(scopes))}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSave} disabled={saving || !name}>
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string | null, fallback: string): string {
  if (!iso) return fallback;
  return new Date(iso).toLocaleDateString();
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function ApiKeysPage() {
  const { t } = useTranslation();
  const { apiKeys, isLoading, createMutation, updateMutation, revokeMutation } = useApiKeys();

  const [showCreate, setShowCreate] = useState(false);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [editKey, setEditKey] = useState<ApiKeySummary | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKeySummary | null>(null);

  async function handleCreate(payload: ApiKeyCreate) {
    const created = await createMutation.mutateAsync(payload);
    setCreatedKey(created as ApiKeyCreated);
  }

  async function handleSaveEdit(payload: ApiKeyUpdate) {
    if (!editKey) return;
    await updateMutation.mutateAsync({ id: editKey.id, payload });
  }

  return (
    <PageShell>
      <PageHeader
        title={t("api_keys.page_title")}
        subtitle={t("api_keys.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("api_keys.add_button")}
          </Button>
        }
      />

      <CreateDialog
        open={showCreate}
        onOpenChange={(v) => {
          setShowCreate(v);
        }}
        onCreate={handleCreate}
      />

      <TokenRevealDialog
        created={createdKey}
        onClose={() => setCreatedKey(null)}
      />

      <EditDialog
        open={!!editKey}
        onOpenChange={(v) => { if (!v) setEditKey(null); }}
        apiKey={editKey}
        onSave={handleSaveEdit}
      />

      <ConfirmDialog
        open={!!revokeTarget}
        onOpenChange={(v) => { if (!v) setRevokeTarget(null); }}
        title={t("api_keys.confirm_revoke_title")}
        description={t("api_keys.confirm_revoke_message", {
          name: revokeTarget?.name ?? "",
        })}
        destructive
        onConfirm={async () => {
          if (revokeTarget) await revokeMutation.mutateAsync(revokeTarget.id);
        }}
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("api_keys.col_name")}</TableHead>
                <TableHead>{t("api_keys.col_prefix")}</TableHead>
                <TableHead>{t("api_keys.col_scopes")}</TableHead>
                <TableHead>{t("api_keys.col_rate_limit")}</TableHead>
                <TableHead>{t("api_keys.col_expires")}</TableHead>
                <TableHead>{t("api_keys.col_last_used")}</TableHead>
                <TableHead>{t("api_keys.col_status")}</TableHead>
                <TableHead className="text-right">{t("api_keys.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(apiKeys ?? []).map((key) => (
                <TableRow key={key.id} className={key.revoked ? "opacity-60" : ""}>
                  <TableCell className="font-medium">{key.name}</TableCell>
                  <TableCell>
                    <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">
                      {key.prefix}…
                    </code>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {t("api_keys.scopes_count", { count: key.scopes.length })}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {key.rate_limit != null
                      ? `${key.rate_limit}${t("api_keys.rate_unit")}`
                      : "—"}
                  </TableCell>
                  <TableCell>
                    {formatDate(key.expires_at, t("api_keys.never_expires"))}
                  </TableCell>
                  <TableCell>
                    {formatDate(key.last_used_at, "—")}
                  </TableCell>
                  <TableCell>
                    {key.revoked ? (
                      <Badge className="bg-red-100 text-red-800 hover:bg-red-100 dark:bg-red-900/40 dark:text-red-300">
                        {t("api_keys.status_revoked")}
                      </Badge>
                    ) : (
                      <Badge className="bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900/40 dark:text-green-300">
                        {t("api_keys.status_active")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {!key.revoked && (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditKey(key)}
                            title={t("api_keys.edit_dialog_title")}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setRevokeTarget(key)}
                            title={t("api_keys.confirm_revoke_title")}
                          >
                            <KeyRound className="w-3.5 h-3.5 text-destructive" />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}
