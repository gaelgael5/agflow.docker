import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Download, KeyRound, ShieldPlus, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { useInfraCertificates } from "@/hooks/useInfra";
import { infraCertificatesApi } from "@/lib/infraApi";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

const selectClass = "mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm";
const textareaClass = "mt-1 flex w-full rounded-md border border-input bg-background px-3 py-2 text-[12px] font-mono ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export function InfraCertificatesPage() {
  const { t } = useTranslation();
  const { certificates, isLoading, createMutation, deleteMutation } = useInfraCertificates();
  const [showGenerate, setShowGenerate] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [generatedPublicKey, setGeneratedPublicKey] = useState<{ name: string; key: string } | null>(null);

  async function copyPublicKey(id: string) {
    try {
      const pub = await infraCertificatesApi.getPublicKey(id);
      await navigator.clipboard.writeText(pub);
      toast.success(t("infra.cert_public_copied"));
    } catch {
      toast.error(t("infra.cert_no_public_key"));
    }
  }

  async function downloadPublicKey(id: string, name: string) {
    try {
      const pub = await infraCertificatesApi.getPublicKey(id);
      const blob = new Blob([pub], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${name}.pub`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("infra.cert_no_public_key"));
    }
  }

  return (
    <PageShell>
      <PageHeader
        title={t("infra.certificates_title")}
        subtitle={t("infra.certificates_subtitle")}
        actions={
          <div className="flex gap-2">
            <Button onClick={() => setShowGenerate(true)}>
              <ShieldPlus className="w-4 h-4" />
              {t("infra.cert_generate")}
            </Button>
            <Button variant="outline" onClick={() => setShowUpload(true)}>
              <Upload className="w-4 h-4" />
              {t("infra.cert_upload")}
            </Button>
          </div>
        }
      />

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("infra.cert_name")}</TableHead>
                <TableHead>{t("infra.cert_key_type")}</TableHead>
                <TableHead>{t("infra.cert_keys")}</TableHead>
                <TableHead>{t("infra.cert_created_at")}</TableHead>
                <TableHead className="text-right">{t("infra.cert_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(certificates ?? []).map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <KeyRound className="w-4 h-4 text-muted-foreground" />
                      <span className="font-medium">{c.name}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[9px] font-mono">
                      {c.key_type === "ed25519" ? "Ed25519" : "RSA 4096"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      {c.has_private_key && <Badge variant="secondary" className="text-[9px]">private</Badge>}
                      {c.has_public_key && <Badge variant="outline" className="text-[9px]">public</Badge>}
                      {c.has_passphrase && <Badge variant="outline" className="text-[9px]">passphrase</Badge>}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-[11px] text-muted-foreground">
                      {new Date(c.created_at).toLocaleDateString()}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {c.has_public_key && (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            title={t("infra.cert_copy_public")}
                            onClick={() => copyPublicKey(c.id)}
                          >
                            <Copy className="w-3 h-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            title={t("infra.cert_download_public")}
                            onClick={() => downloadPublicKey(c.id, c.name)}
                          >
                            <Download className="w-3 h-3" />
                          </Button>
                        </>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => setDeleteTarget({ id: c.id, name: c.name })}
                      >
                        <Trash2 className="w-3 h-3 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {/* Generate dialog */}
      <GenerateDialog
        open={showGenerate}
        onClose={() => setShowGenerate(false)}
        onGenerated={(name, publicKey) => {
          setShowGenerate(false);
          setGeneratedPublicKey({ name, key: publicKey });
        }}
        t={t}
      />

      {/* Upload dialog */}
      <UploadDialog
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onCreate={async (p) => {
          await createMutation.mutateAsync(p);
          setShowUpload(false);
        }}
        t={t}
      />

      {/* Public key result dialog */}
      <PublicKeyResultDialog
        data={generatedPublicKey}
        onClose={() => setGeneratedPublicKey(null)}
        t={t}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(o) => { if (!o) setDeleteTarget(null); }}
        title={t("infra.cert_delete_title")}
        description={t("infra.cert_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
        }}
      />
    </PageShell>
  );
}

/* ── Generate Dialog ──────────────────────────────────── */

function GenerateDialog({ open, onClose, onGenerated, t }: {
  open: boolean;
  onClose: () => void;
  onGenerated: (name: string, publicKey: string) => void;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [keyType, setKeyType] = useState<"rsa" | "ed25519">("ed25519");
  const [passphrase, setPassphrase] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(""); setKeyType("ed25519"); setPassphrase("");
    setSaving(false);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.cert_generate_title")}</DialogTitle>
          <DialogDescription>{t("infra.cert_generate_desc")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.cert_name")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.cert_key_type")}</Label>
            <select value={keyType} onChange={(e) => setKeyType(e.target.value as "rsa" | "ed25519")} className={selectClass}>
              <option value="ed25519">Ed25519 (recommended)</option>
              <option value="rsa">RSA 4096</option>
            </select>
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.cert_passphrase")}</Label>
            <Input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} className="mt-1" placeholder={t("infra.cert_passphrase_optional")} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                const result = await infraCertificatesApi.generate({
                  name: name.trim(),
                  key_type: keyType,
                  passphrase: passphrase || undefined,
                });
                toast.success(`${t("infra.cert_generated")} (${keyType})`);
                onGenerated(name.trim(), result.public_key);
              } catch (e) {
                toast.error(String(e));
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? "..." : t("infra.cert_generate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Upload Dialog ────────────────────────────────────── */

function UploadDialog({ open, onClose, onCreate, t }: {
  open: boolean;
  onClose: () => void;
  onCreate: (p: { name: string; private_key: string; public_key?: string; passphrase?: string }) => Promise<void>;
  t: (key: string) => string;
}) {
  const [name, setName] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [publicKey, setPublicKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setName(""); setPrivateKey(""); setPublicKey(""); setPassphrase("");
    setSaving(false);
  }, [open]);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = reader.result as string;
      setPrivateKey(text);
      if (!name) setName(file.name.replace(/\.(pem|key|id_rsa|id_ed25519)$/i, ""));
    };
    reader.readAsText(file);
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.cert_upload_title")}</DialogTitle>
          <DialogDescription>{t("infra.cert_upload_desc")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="text-[11px]">{t("infra.cert_name")}</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} className="mt-1" autoFocus />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.cert_private_key")}</Label>
            <div className="flex gap-2 mt-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="w-3.5 h-3.5" />
                {t("infra.cert_choose_file")}
              </Button>
              <input ref={fileRef} type="file" className="hidden" accept=".pem,.key,*" onChange={handleFile} />
              {privateKey && <Badge variant="secondary" className="text-[9px] self-center">{t("infra.cert_file_loaded")}</Badge>}
            </div>
            <textarea
              value={privateKey}
              onChange={(e) => setPrivateKey(e.target.value)}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              rows={4}
              className={textareaClass}
            />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.cert_public_key")}</Label>
            <textarea
              value={publicKey}
              onChange={(e) => setPublicKey(e.target.value)}
              placeholder="ssh-ed25519 AAAA... or ssh-rsa AAAA..."
              rows={2}
              className={textareaClass}
            />
          </div>
          <div>
            <Label className="text-[11px]">{t("infra.cert_passphrase")}</Label>
            <Input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} className="mt-1" placeholder={t("infra.cert_passphrase_optional")} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            disabled={!name.trim() || !privateKey.trim() || saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onCreate({
                  name: name.trim(),
                  private_key: privateKey,
                  public_key: publicKey || undefined,
                  passphrase: passphrase || undefined,
                });
                toast.success(t("infra.cert_uploaded"));
              } catch (e) {
                toast.error(String(e));
              } finally {
                setSaving(false);
              }
            }}
          >
            {saving ? "..." : t("infra.cert_upload")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ── Public Key Result Dialog ─────────────────────────── */

function PublicKeyResultDialog({ data, onClose, t }: {
  data: { name: string; key: string } | null;
  onClose: () => void;
  t: (key: string) => string;
}) {
  async function copy() {
    if (!data) return;
    await navigator.clipboard.writeText(data.key);
    toast.success(t("infra.cert_public_copied"));
  }

  return (
    <Dialog open={data !== null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t("infra.cert_generated_title")}</DialogTitle>
          <DialogDescription>{t("infra.cert_generated_desc")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label className="text-[11px]">{t("infra.cert_public_key")}</Label>
          <textarea
            readOnly
            value={data?.key ?? ""}
            rows={3}
            className={`${textareaClass} bg-muted`}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            <Copy className="w-3.5 h-3.5" />
            {t("infra.cert_copy_public")}
          </Button>
          <Button onClick={onClose}>{t("common.confirm")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
