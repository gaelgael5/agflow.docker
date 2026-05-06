import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Eye, EyeOff, Copy, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useUserSecrets } from "@/hooks/useUserSecrets";
import { userSecretsApi } from "@/lib/userSecretsApi";
import { useToast } from "@/hooks/use-toast";

function AddDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { createMutation } = useUserSecrets();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = () => {
    createMutation.mutate({ name, value, description: description || undefined }, {
      onSuccess: () => { setName(""); setValue(""); setDescription(""); onClose(); },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t("my_secrets.add_dialog_title")}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label>{t("my_secrets.field_name")}</Label><Input value={name} onChange={e => setName(e.target.value)} placeholder="MY_API_KEY" /></div>
          <div><Label>{t("my_secrets.field_value")}</Label><Input type="password" value={value} onChange={e => setValue(e.target.value)} /></div>
          <div><Label>{t("my_secrets.field_description")}</Label><Input value={description} onChange={e => setDescription(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button onClick={handleSubmit} disabled={!name || !value || createMutation.isPending}>{t("common.save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditDialog({ name, open, onClose }: { name: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { updateMutation } = useUserSecrets();
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    updateMutation.mutate({ name, value }, { onSuccess: onClose });
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t("my_secrets.edit_dialog_title")}: {name}</DialogTitle></DialogHeader>
        <div><Label>{t("my_secrets.field_value")}</Label><Input type="password" value={value} onChange={e => setValue(e.target.value)} /></div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button onClick={handleSubmit} disabled={!value || updateMutation.isPending}>{t("common.save")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MySecretsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { listQuery, deleteMutation } = useUserSecrets();
  const [addOpen, setAddOpen] = useState(false);
  const [editName, setEditName] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [revealing, setRevealing] = useState<string | null>(null);

  const handleReveal = async (name: string) => {
    if (revealed[name]) { setRevealed(r => { const n = { ...r }; delete n[name]; return n; }); return; }
    setRevealing(name);
    try {
      const data = await userSecretsApi.reveal(name);
      setRevealed(r => ({ ...r, [name]: data.value }));
    } catch { toast({ variant: "destructive", description: t("my_secrets.reveal_error") }); }
    finally { setRevealing(null); }
  };

  const handleCopy = (value: string) => {
    navigator.clipboard.writeText(value);
    toast({ description: t("my_secrets.copy_success") });
  };

  const secrets = listQuery.data ?? [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{t("my_secrets.page_title")}</h1>
          <p className="text-sm text-muted-foreground">{t("my_secrets.page_subtitle")}</p>
        </div>
        <Button onClick={() => setAddOpen(true)}><Plus className="w-4 h-4 mr-2" />{t("my_secrets.add_button")}</Button>
      </div>

      {listQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      ) : secrets.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("my_secrets.empty")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("my_secrets.col_name")}</TableHead>
              <TableHead>{t("my_secrets.col_value")}</TableHead>
              <TableHead className="w-40">{t("my_secrets.col_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {secrets.map(s => (
              <TableRow key={s.name}>
                <TableCell className="font-mono text-sm">{s.name}</TableCell>
                <TableCell className="font-mono text-sm">
                  {revealed[s.name] ? revealed[s.name] : "••••••••"}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button size="icon" variant="ghost" onClick={() => handleReveal(s.name)} disabled={revealing === s.name}>
                      {revealed[s.name] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </Button>
                    {revealed[s.name] && (
                      <Button size="icon" variant="ghost" onClick={() => handleCopy(revealed[s.name])}>
                        <Copy className="w-4 h-4" />
                      </Button>
                    )}
                    <Button size="icon" variant="ghost" onClick={() => setEditName(s.name)}>
                      <Pencil className="w-4 h-4" />
                    </Button>
                    <Button size="icon" variant="ghost" className="text-destructive" onClick={() => deleteMutation.mutate(s.name)}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} />
      {editName && <EditDialog name={editName} open={true} onClose={() => setEditName(null)} />}
    </div>
  );
}
