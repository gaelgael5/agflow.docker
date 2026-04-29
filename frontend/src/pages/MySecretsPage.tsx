import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Eye, EyeOff, KeyRound, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useVault } from "@/hooks/useVault";
import { useUserSecrets } from "@/hooks/useUserSecrets";
import { VaultSetupDialog } from "@/components/VaultSetupDialog";
import { VaultUnlockDialog } from "@/components/VaultUnlockDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { UserSecretSummary } from "@/lib/userSecretsApi";

const USER_EMAIL = "admin@agflow.example.com";

// ─── Add dialog ─────────────────────────────────────────────────────────────

interface AddDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string, value: string) => Promise<void>;
}

function AddDialog({ open, onOpenChange, onSubmit }: AddDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset when dialog opens
  useEffect(() => {
    if (open) {
      setName("");
      setValue("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(name.trim(), value);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("my_secrets.decrypt_error"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("my_secrets.add_dialog_title")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="add-secret-name">{t("my_secrets.field_name")}</Label>
              <Input
                id="add-secret-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="MY_API_KEY"
                required
                autoFocus
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="add-secret-value">{t("my_secrets.field_value")}</Label>
              <Input
                id="add-secret-value"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
          <DialogFooter className="mt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={submitting}>
              {t("common.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Edit dialog ─────────────────────────────────────────────────────────────

interface EditDialogProps {
  open: boolean;
  secret: UserSecretSummary | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (id: string, value: string) => Promise<void>;
}

function EditDialog({ open, secret, onOpenChange, onSubmit }: EditDialogProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setValue("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!secret) return;
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(secret.id, value);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("my_secrets.decrypt_error"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("my_secrets.edit_dialog_title")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label>{t("my_secrets.field_name")}</Label>
              <Input value={secret?.name ?? ""} readOnly className="font-mono bg-muted/50" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="edit-secret-value">{t("my_secrets.field_value")}</Label>
              <Input
                id="edit-secret-value"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoComplete="new-password"
                autoFocus
                required
              />
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
          <DialogFooter className="mt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={submitting}>
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── Secrets table ────────────────────────────────────────────────────────────

interface SecretsTableProps {
  secrets: UserSecretSummary[];
  decrypted: Record<string, string>;
  onEdit: (secret: UserSecretSummary) => void;
  onDelete: (secret: UserSecretSummary) => void;
}

function SecretsTable({ secrets, decrypted, onEdit, onDelete }: SecretsTableProps) {
  const { t } = useTranslation();
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  function toggleReveal(id: string) {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function copyValue(secret: UserSecretSummary) {
    const plain = decrypted[secret.id];
    if (plain === undefined || plain === `⚠ ${t("my_secrets.decrypt_error")}`) {
      toast.error(t("my_secrets.copy_error"));
      return;
    }
    try {
      await navigator.clipboard.writeText(plain);
      toast.success(t("my_secrets.copy_success", { name: secret.name }));
    } catch {
      toast.error(t("my_secrets.copy_error"));
    }
  }

  async function copyName(secret: UserSecretSummary) {
    const ref = `\${${secret.name}}`;
    try {
      await navigator.clipboard.writeText(ref);
      toast.success(t("my_secrets.copy_name_success", { name: ref }));
    } catch {
      toast.error(t("my_secrets.copy_error"));
    }
  }

  function maskedValue(id: string): string {
    const plain = decrypted[id];
    if (plain === undefined) return "••••••••";
    if (plain === `⚠ ${t("my_secrets.decrypt_error")}`) return plain;
    return plain.slice(0, 4) + "••••";
  }

  if (secrets.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        {t("my_secrets.empty")}
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("my_secrets.col_name")}</TableHead>
          <TableHead>{t("my_secrets.col_value")}</TableHead>
          <TableHead className="text-right">{t("my_secrets.col_actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {secrets.map((s) => {
          const isRevealed = revealed.has(s.id);
          return (
            <TableRow key={s.id}>
              <TableCell className="font-mono text-sm">{s.name}</TableCell>
              <TableCell className="font-mono text-sm">
                {isRevealed ? (decrypted[s.id] ?? "••••••••") : maskedValue(s.id)}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void copyName(s)}
                    title={t("my_secrets.copy_name_button")}
                  >
                    <KeyRound className="h-4 w-4" />
                    <span className="sr-only">{t("my_secrets.copy_name_button")}</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggleReveal(s.id)}
                    title={isRevealed ? t("my_secrets.hide_button") : t("my_secrets.reveal_button")}
                  >
                    {isRevealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    <span className="sr-only">
                      {isRevealed ? t("my_secrets.hide_button") : t("my_secrets.reveal_button")}
                    </span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void copyValue(s)}
                    title={t("my_secrets.copy_button")}
                  >
                    <Copy className="h-4 w-4" />
                    <span className="sr-only">{t("my_secrets.copy_button")}</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onEdit(s)}
                    title={t("my_secrets.edit_button")}
                  >
                    <Pencil className="h-4 w-4" />
                    <span className="sr-only">{t("my_secrets.edit_button")}</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onDelete(s)}
                    title={t("my_secrets.delete_button")}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                    <span className="sr-only">{t("my_secrets.delete_button")}</span>
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function MySecretsPage() {
  const { t } = useTranslation();
  const vault = useVault();
  const { secrets, isLoading, createMutation, updateMutation, deleteMutation } = useUserSecrets();

  // Decrypted cache
  const [decrypted, setDecrypted] = useState<Record<string, string>>({});

  // Dialog states
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<UserSecretSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserSecretSummary | null>(null);

  // Decrypt all secrets when vault is unlocked and secrets are loaded
  useEffect(() => {
    if (vault.state !== "unlocked" || !secrets) return;
    let cancelled = false;

    function decryptAll() {
      const results: Record<string, string> = {};
      for (const s of secrets ?? []) {
        try {
          results[s.id] = vault.decryptSecret(s.ciphertext, s.iv);
        } catch {
          results[s.id] = `⚠ ${t("my_secrets.decrypt_error")}`;
        }
      }
      if (!cancelled) setDecrypted(results);
    }

    decryptAll();
    return () => {
      cancelled = true;
    };
  }, [vault.state, secrets, vault, t]);

  // ── Handlers ──

  async function handleAdd(name: string, value: string) {
    const { ciphertext, iv } = vault.encryptSecret(value);
    await createMutation.mutateAsync({ name, ciphertext, iv });
  }

  async function handleEdit(id: string, value: string) {
    const { ciphertext, iv } = vault.encryptSecret(value);
    await updateMutation.mutateAsync({ id, payload: { ciphertext, iv } });
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    await deleteMutation.mutateAsync(deleteTarget.id);
  }

  // ── Vault overlay states ──

  if (vault.state === "loading") {
    return (
      <PageShell>
        <div className="space-y-3">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-96" />
          <Skeleton className="h-48 w-full mt-6" />
        </div>
      </PageShell>
    );
  }

  if (vault.state === "error") {
    return (
      <PageShell>
        <div className="space-y-4 max-w-xl">
          <h2 className="text-lg font-semibold text-destructive">
            {t("my_secrets.vault_status_error")}
          </h2>
          {vault.lastError && (
            <p className="text-sm text-muted-foreground break-all">{vault.lastError}</p>
          )}
          <Button onClick={() => vault.refreshStatus()}>{t("my_secrets.retry")}</Button>
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <VaultSetupDialog
        open={vault.state === "uninitialized"}
        email={USER_EMAIL}
        onComplete={() => undefined}
      />

      <VaultUnlockDialog
        open={vault.state === "locked"}
        email={USER_EMAIL}
        onComplete={() => undefined}
      />

      <PageHeader
        title={t("my_secrets.page_title")}
        subtitle={t("my_secrets.page_subtitle")}
        actions={
          vault.state === "unlocked" ? (
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-emerald-600 border-emerald-400 dark:text-emerald-400">
                🔓 {t("my_secrets.vault_unlocked")}
              </Badge>
              <Button variant="outline" size="sm" onClick={vault.lockVault}>
                {t("my_secrets.lock_button")}
              </Button>
              <Button size="sm" onClick={() => setAddOpen(true)}>
                {t("my_secrets.add_button")}
              </Button>
            </div>
          ) : undefined
        }
      />

      {vault.state === "unlocked" && (
        <>
          <Card>
            <CardContent className="p-0">
              {isLoading ? (
                <div className="space-y-3 p-6">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ) : (
                <SecretsTable
                  secrets={secrets ?? []}
                  decrypted={decrypted}
                  onEdit={setEditTarget}
                  onDelete={setDeleteTarget}
                />
              )}
            </CardContent>
          </Card>

          <AddDialog
            open={addOpen}
            onOpenChange={setAddOpen}
            onSubmit={handleAdd}
          />

          <EditDialog
            open={editTarget !== null}
            secret={editTarget}
            onOpenChange={(open) => { if (!open) setEditTarget(null); }}
            onSubmit={handleEdit}
          />

          <ConfirmDialog
            open={deleteTarget !== null}
            onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
            title={t("my_secrets.delete_button")}
            description={t("my_secrets.confirm_delete", { name: deleteTarget?.name ?? "" })}
            confirmLabel={t("my_secrets.delete_button")}
            destructive
            onConfirm={handleDelete}
          />
        </>
      )}
    </PageShell>
  );
}
