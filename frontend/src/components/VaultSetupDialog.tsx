import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
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
import { useVault } from "@/hooks/useVault";

interface VaultSetupDialogProps {
  open: boolean;
  email: string;
  onComplete: () => void;
}

export function VaultSetupDialog({ open, email, onComplete }: VaultSetupDialogProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const vault = useVault();

  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);

    if (passphrase.length < 8) {
      setError(t("vault.setup_min_length"));
      return;
    }
    if (passphrase !== confirm) {
      setError(t("vault.setup_mismatch"));
      return;
    }

    setSubmitting(true);
    try {
      await vault.setupVault(passphrase);
      setPassphrase("");
      setConfirm("");
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vault.setup_error_generic"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{t("vault.setup_title")}</DialogTitle>
          <DialogDescription asChild>
            <div className="rounded-md border border-amber-400 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-200">
              {t("vault.setup_warning")}
            </div>
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} autoComplete="on">
          {/* Hidden username field for password manager compatibility */}
          <input
            type="hidden"
            name="username"
            autoComplete="username"
            value={email}
            readOnly
          />

          <div className="flex flex-col gap-4 py-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="vault-passphrase">{t("vault.setup_passphrase")}</Label>
              <Input
                id="vault-passphrase"
                type="password"
                name="password"
                autoComplete="new-password"
                minLength={8}
                required
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="vault-confirm">{t("vault.setup_confirm")}</Label>
              <Input
                id="vault-confirm"
                type="password"
                name="password-confirm"
                autoComplete="new-password"
                minLength={8}
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>

            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>

          <DialogFooter className="mt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate("/")}
              disabled={submitting}
            >
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={submitting}>
              {t("vault.setup_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
