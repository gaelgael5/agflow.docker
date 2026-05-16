import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plug, Star, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useHarpocrateVaults } from "@/hooks/useHarpocrateVaults";
import { harpocrateVaultsApi, type HarpocrateVaultSummary } from "@/lib/harpocrateVaultsApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface FormState {
  id?: string;
  name: string;
  base_url: string;
  api_key_id: string;
  api_key: string;
  is_default: boolean;
}

const EMPTY: FormState = {
  name: "",
  base_url: "https://vault.yoops.org",
  api_key_id: "default",
  api_key: "",
  is_default: false,
};

export function HarpocrateVaultsTab() {
  const { t } = useTranslation();
  const { vaults, isLoading, create, update, remove, setDefault } = useHarpocrateVaults();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [confirmDelete, setConfirmDelete] = useState<HarpocrateVaultSummary | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  const openCreate = () => {
    setForm(EMPTY);
    setOpen(true);
  };

  const openEdit = (v: HarpocrateVaultSummary) => {
    setForm({
      id: v.id,
      name: v.name,
      base_url: v.base_url,
      api_key_id: v.api_key_id,
      api_key: "",
      is_default: v.is_default,
    });
    setOpen(true);
  };

  const handleSubmit = async () => {
    try {
      if (form.id) {
        const payload = {
          name: form.name,
          base_url: form.base_url,
          api_key_id: form.api_key_id,
          is_default: form.is_default,
          ...(form.api_key ? { api_key: form.api_key } : {}),
        };
        await update({ id: form.id, payload });
        toast.success(t("settings.harpocrate.updated"));
      } else {
        if (!form.api_key) {
          toast.error(t("settings.harpocrate.api_key_required"));
          return;
        }
        await create({
          name: form.name,
          base_url: form.base_url,
          api_key_id: form.api_key_id,
          api_key: form.api_key,
          is_default: form.is_default,
        });
        toast.success(t("settings.harpocrate.created"));
      }
      setOpen(false);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(msg);
    }
  };

  const handleSetDefault = async (v: HarpocrateVaultSummary) => {
    try {
      await setDefault(v.id);
      toast.success(t("settings.harpocrate.default_set", { name: v.name }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(msg);
    }
  };

  const handleTestConnection = async (v: HarpocrateVaultSummary) => {
    setTesting(v.id);
    try {
      const result = await harpocrateVaultsApi.testConnection(v.id);
      if (result.ok) {
        toast.success(t("settings.harpocrate.test_ok", { name: v.name }));
      } else {
        toast.error(t("settings.harpocrate.test_failed", { error: result.error ?? "?" }));
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(msg);
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await remove(confirmDelete.id);
      toast.success(t("settings.harpocrate.deleted", { name: confirmDelete.name }));
      setConfirmDelete(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(msg);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("settings.harpocrate.title")}</CardTitle>
        <Button onClick={openCreate}>{t("settings.harpocrate.add")}</Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : vaults.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("settings.harpocrate.empty")}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.harpocrate.col_name")}</TableHead>
                <TableHead>{t("settings.harpocrate.col_url")}</TableHead>
                <TableHead>{t("settings.harpocrate.col_api_key_id")}</TableHead>
                <TableHead>{t("settings.harpocrate.col_default")}</TableHead>
                <TableHead className="text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {vaults.map((v) => (
                <TableRow key={v.id}>
                  <TableCell className="font-medium">{v.name}</TableCell>
                  <TableCell className="font-mono text-xs">{v.base_url}</TableCell>
                  <TableCell className="font-mono text-xs">{v.api_key_id}</TableCell>
                  <TableCell>
                    {v.is_default ? (
                      <Badge variant="default" className="gap-1">
                        <Star className="h-3 w-3" />
                        {t("settings.harpocrate.is_default")}
                      </Badge>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSetDefault(v)}
                        title={t("settings.harpocrate.set_default")}
                      >
                        <Star className="h-4 w-4" />
                      </Button>
                    )}
                  </TableCell>
                  <TableCell className="text-right space-x-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleTestConnection(v)}
                      disabled={testing === v.id}
                      title={t("settings.harpocrate.test_connection")}
                    >
                      {testing === v.id ? (
                        <Plug className="h-4 w-4 animate-pulse" />
                      ) : (
                        <Plug className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEdit(v)}
                      title={t("common.edit")}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmDelete(v)}
                      title={t("common.delete")}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {form.id
                ? t("settings.harpocrate.edit_title")
                : t("settings.harpocrate.create_title")}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="vault-name">{t("settings.harpocrate.col_name")}</Label>
              <Input
                id="vault-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="default"
              />
            </div>
            <div>
              <Label htmlFor="vault-url">{t("settings.harpocrate.col_url")}</Label>
              <Input
                id="vault-url"
                value={form.base_url}
                onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                placeholder="https://vault.example.com"
              />
            </div>
            <div>
              <Label htmlFor="vault-api-key-id">
                {t("settings.harpocrate.col_api_key_id")}
              </Label>
              <Input
                id="vault-api-key-id"
                value={form.api_key_id}
                onChange={(e) => setForm((f) => ({ ...f, api_key_id: e.target.value }))}
                placeholder="default"
              />
            </div>
            <div>
              <Label htmlFor="vault-api-key">
                {form.id
                  ? t("settings.harpocrate.api_key_optional")
                  : t("settings.harpocrate.api_key")}
              </Label>
              <Input
                id="vault-api-key"
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                placeholder="hrpv_1_..."
                autoComplete="new-password"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                id="vault-default"
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
                className="h-4 w-4 rounded border-input"
              />
              <Label htmlFor="vault-default">{t("settings.harpocrate.set_default")}</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={handleSubmit} disabled={!form.name || !form.base_url}>
              {form.id ? t("common.save") : t("common.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(o) => !o && setConfirmDelete(null)}
        title={t("settings.harpocrate.delete_title")}
        description={t("settings.harpocrate.delete_description", {
          name: confirmDelete?.name ?? "",
        })}
        confirmLabel={t("common.delete")}
        onConfirm={handleDelete}
      />
    </Card>
  );
}
