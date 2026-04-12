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

interface VaultUnlockDialogProps {
  open: boolean;
  email: string;
  onComplete: () => void;
}

export function VaultUnlockDialog({ open, email, onComplete }: VaultUnlockDialogProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const vault = useVault();

  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const ok = await vault.unlockVault(passphrase);
      if (!ok) {
        setError(t("vault.unlock_error"));
        return;
      }
      setPassphrase("");
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vault.unlock_error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      <DialogContent onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{t("vault.unlock_title")}</DialogTitle>
          <DialogDescription>{t("vault.unlock_subtitle")}</DialogDescription>
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
              <Label htmlFor="vault-passphrase">{t("vault.unlock_passphrase")}</Label>
              <Input
                id="vault-passphrase"
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
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
              {t("vault.unlock_submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
