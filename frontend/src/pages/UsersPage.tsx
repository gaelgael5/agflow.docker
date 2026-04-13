import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Shield, UserCheck, UserX, RefreshCw, Trash2 } from "lucide-react";
import { useUsers } from "@/hooks/useUsers";
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
  DialogDescription,
  DialogHeader,
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
import type { UserSummary } from "@/lib/usersApi";
import { ScopesEditor } from "@/components/ScopesEditor";
import { useScopes } from "@/hooks/useScopes";

// ─── Scope catalogue ─────────────────────────────────────────────────────────

const STANDARD_PROFILE_SCOPES = [
  "roles:read",
  "roles:write",
  "catalogs:read",
  "agents:read",
  "agents:run",
  "containers:read",
  "containers:run",
  "containers.logs:read",
  "containers.chat:read",
  "containers.chat:write",
  "keys:manage",
];

// ─── Scopes Dialog ────────────────────────────────────────────────────────────

interface ScopesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: UserSummary | null;
  onSave: (scopes: string[]) => Promise<void>;
}

function ScopesDialog({ open, onOpenChange, user, onSave }: ScopesDialogProps) {
  const { t } = useTranslation();
  const { allScopes } = useScopes();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  // Sync state when dialog opens for a user
  function handleOpenChange(val: boolean) {
    if (val && user) {
      setChecked(new Set(user.scopes));
    }
    onOpenChange(val);
  }

  function applyStandard() {
    setChecked(new Set(STANDARD_PROFILE_SCOPES));
  }

  function checkAll() {
    setChecked(new Set(allScopes));
  }

  function uncheckAll() {
    setChecked(new Set(["keys:manage"]));
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave([...checked]);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("users.scopes_dialog_title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("users.scopes_dialog_title")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={applyStandard}>
            {t("users.scopes_standard_profile")}
          </Button>
          <Button variant="outline" size="sm" onClick={checkAll}>
            {t("users.scopes_check_all")}
          </Button>
          <Button variant="outline" size="sm" onClick={uncheckAll}>
            {t("users.scopes_uncheck_all")}
          </Button>
        </div>

        <div className="flex-1 overflow-hidden">
          <ScopesEditor
            selected={[...checked]}
            onChange={(scopes) => setChecked(new Set(scopes))}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {t("users.scopes_save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Create Dialog ────────────────────────────────────────────────────────────

interface CreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (payload: {
    email: string;
    name: string;
    role: string;
    scopes: string[];
    status: "approved";
  }) => Promise<void>;
}

function CreateDialog({ open, onOpenChange, onCreate }: CreateDialogProps) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("user");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setEmail("");
    setName("");
    setRole("user");
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
      await onCreate({
        email,
        name,
        role,
        scopes: STANDARD_PROFILE_SCOPES,
        status: "approved",
      });
      handleOpenChange(false);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setError(detail ?? t("common.confirm"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("users.create_dialog_title")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("users.create_dialog_title")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="user-email">{t("users.create_email")}</Label>
            <Input
              id="user-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="user-name">{t("users.create_name")}</Label>
            <Input
              id="user-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>{t("users.create_role")}</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">{t("users.role_user")}</SelectItem>
                <SelectItem value="admin">{t("users.role_admin")}</SelectItem>
              </SelectContent>
            </Select>
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
          <Button onClick={handleSubmit} disabled={submitting || !email}>
            {t("common.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: UserSummary["status"] }) {
  const { t } = useTranslation();
  if (status === "pending")
    return (
      <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100 dark:bg-amber-900/40 dark:text-amber-300">
        {t("users.status_pending")}
      </Badge>
    );
  if (status === "approved")
    return (
      <Badge className="bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900/40 dark:text-green-300">
        {t("users.status_active")}
      </Badge>
    );
  return <Badge variant="secondary">{t("users.status_disabled")}</Badge>;
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function UsersPage() {
  const { t } = useTranslation();
  const {
    users,
    isLoading,
    createMutation,
    updateMutation,
    approveMutation,
    disableMutation,
    enableMutation,
    deleteMutation,
  } = useUsers();

  const [showCreate, setShowCreate] = useState(false);
  const [scopesUser, setScopesUser] = useState<UserSummary | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UserSummary | null>(null);

  async function handleCreate(payload: {
    email: string;
    name: string;
    role: string;
    scopes: string[];
    status: "approved";
  }) {
    await createMutation.mutateAsync(payload);
  }

  async function handleSaveScopes(scopes: string[]) {
    if (!scopesUser) return;
    await updateMutation.mutateAsync({ id: scopesUser.id, payload: { scopes } });
  }

  return (
    <PageShell>
      <PageHeader
        title={t("users.page_title")}
        subtitle={t("users.page_subtitle")}
        actions={
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" />
            {t("users.add_button")}
          </Button>
        }
      />

      <CreateDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        onCreate={handleCreate}
      />

      <ScopesDialog
        open={!!scopesUser}
        onOpenChange={(v) => { if (!v) setScopesUser(null); }}
        user={scopesUser}
        onSave={handleSaveScopes}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
        title={t("users.delete_button")}
        description={t("users.confirm_delete", {
          name: deleteTarget?.name ?? deleteTarget?.email ?? "",
        })}
        destructive
        onConfirm={async () => {
          if (deleteTarget) await deleteMutation.mutateAsync(deleteTarget.id);
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
                <TableHead>{t("users.col_name")}</TableHead>
                <TableHead>{t("users.col_role")}</TableHead>
                <TableHead>{t("users.col_scopes")}</TableHead>
                <TableHead>{t("users.col_status")}</TableHead>
                <TableHead>{t("users.col_keys")}</TableHead>
                <TableHead className="text-right">{t("users.col_actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(users ?? []).map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="font-medium">{user.name || user.email}</div>
                    {user.name && (
                      <div className="text-[12px] text-muted-foreground">{user.email}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    {user.role === "admin" ? (
                      <Badge>{t("users.role_admin")}</Badge>
                    ) : (
                      <Badge variant="secondary">{t("users.role_user")}</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {t("users.scopes_count", { count: user.scopes.length })}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={user.status} />
                  </TableCell>
                  <TableCell>{user.api_key_count}</TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {user.status === "pending" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => approveMutation.mutate(user.id)}
                          title={t("users.approve_button")}
                        >
                          <UserCheck className="w-3.5 h-3.5 text-green-600" />
                        </Button>
                      )}
                      {user.status === "approved" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => disableMutation.mutate(user.id)}
                          title={t("users.disable_button")}
                        >
                          <UserX className="w-3.5 h-3.5 text-amber-600" />
                        </Button>
                      )}
                      {user.status === "disabled" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => enableMutation.mutate(user.id)}
                          title={t("users.enable_button")}
                        >
                          <RefreshCw className="w-3.5 h-3.5 text-blue-600" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setScopesUser(user)}
                        title={t("users.permissions_button")}
                      >
                        <Shield className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(user)}
                        title={t("users.delete_button")}
                      >
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
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
