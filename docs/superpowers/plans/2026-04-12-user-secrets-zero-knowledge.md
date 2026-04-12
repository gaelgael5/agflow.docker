# User Secrets Zero-Knowledge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement per-user encrypted secrets vault with zero-knowledge client-side encryption (AES-256-GCM via WebCrypto), passphrase-based key derivation (PBKDF2), and integration with agent launch for secret injection.

**Architecture:** Frontend handles all crypto (derive key, encrypt, decrypt) via WebCrypto API. Backend is a blind blob store — never sees plaintext. Passphrase verification uses a test ciphertext ("VAULT_OK") decrypted client-side. At agent launch, frontend decrypts secrets locally and sends plaintext via HTTPS for transient injection into the container.

**Tech Stack:** WebCrypto API (PBKDF2 + AES-256-GCM), Python/FastAPI (blob endpoints), React/TypeScript (vault context + page), asyncpg

**Spec:** `docs/superpowers/specs/2026-04-12-user-secrets-zero-knowledge.md`

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/migrations/026_user_vault.sql` | ALTER users + vault columns |
| `backend/migrations/027_user_secrets.sql` | user_secrets table |
| `backend/src/agflow/schemas/user_secrets.py` | Pydantic DTOs for vault + secrets |
| `backend/src/agflow/services/user_secrets_service.py` | CRUD for encrypted blobs |
| `backend/src/agflow/api/admin/vault.py` | Vault setup/status endpoints |
| `backend/src/agflow/api/admin/user_secrets.py` | User secrets CRUD endpoints |
| `backend/tests/test_user_secrets_service.py` | Service tests |
| `frontend/src/lib/vault.ts` | WebCrypto: PBKDF2 key derivation, AES-GCM encrypt/decrypt |
| `frontend/src/hooks/useVault.ts` | React context for vault lock/unlock state + CryptoKey |
| `frontend/src/lib/userSecretsApi.ts` | API client for vault + secrets endpoints |
| `frontend/src/hooks/useUserSecrets.ts` | React Query hook |
| `frontend/src/pages/MySecretsPage.tsx` | "Mes secrets" page |
| `frontend/src/components/VaultSetupDialog.tsx` | Passphrase creation dialog |
| `frontend/src/components/VaultUnlockDialog.tsx` | Session unlock dialog |

### Modified files

| File | Change |
|---|---|
| `backend/src/agflow/main.py` | Register vault + user_secrets routers |
| `backend/src/agflow/services/api_keys_service.py` | Rename `secrets:*` → `platform_secrets:*`, add `user_secrets:*` in ALL_SCOPES |
| `backend/src/agflow/api/admin/containers.py` | Add `secrets` field to TaskRequest |
| `backend/src/agflow/services/container_runner.py` | Merge user secrets into container env vars |
| `frontend/src/components/ScopesEditor.tsx` | Rename secrets group + add user_secrets group |
| `frontend/src/App.tsx` | Add `/my-secrets` route |
| `frontend/src/components/layout/Sidebar.tsx` | Add "Mes secrets" entry |
| `frontend/src/i18n/fr.json` | i18n keys |
| `frontend/src/i18n/en.json` | i18n keys |

---

## Task 1: Migrations

**Files:**
- Create: `backend/migrations/026_user_vault.sql`
- Create: `backend/migrations/027_user_secrets.sql`

- [ ] **Step 1: Write migration 026 — vault columns on users**

```sql
-- 026_user_vault.sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_salt TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_test_ciphertext TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_test_iv TEXT;
```

- [ ] **Step 2: Write migration 027 — user_secrets table**

```sql
-- 027_user_secrets.sql
CREATE TABLE IF NOT EXISTS user_secrets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    ciphertext  TEXT NOT NULL,
    iv          TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_user_secrets_user ON user_secrets(user_id);
```

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/026_user_vault.sql backend/migrations/027_user_secrets.sql
git commit -m "feat(db): migrations 026-027 user vault columns + user_secrets table"
```

---

## Task 2: Rename scopes (secrets → platform_secrets + user_secrets)

**Files:**
- Modify: `backend/src/agflow/services/api_keys_service.py` (lines 16-49, ALL_SCOPES)
- Modify: `frontend/src/components/ScopesEditor.tsx` (lines 16-99, SCOPE_GROUPS)

- [ ] **Step 1: Update ALL_SCOPES in api_keys_service.py**

In the `ALL_SCOPES` set, replace:
- `"secrets:read"` → `"platform_secrets:read"`
- `"secrets:write"` → `"platform_secrets:write"`

Add:
- `"user_secrets:read"`
- `"user_secrets:write"`

- [ ] **Step 2: Update ScopesEditor.tsx**

In the SCOPE_GROUPS array:
- Rename the `secrets` group to `platform_secrets`, update scope keys to `platform_secrets:read` / `platform_secrets:write`
- Add a new group `user_secrets` after `platform_secrets` with scopes `user_secrets:read` and `user_secrets:write`

- [ ] **Step 3: Add scope descriptions to i18n**

In both fr.json and en.json `scope_descriptions` section, add:
```json
"platform_secrets:read": "Consulter les noms des secrets plateforme",
"platform_secrets:write": "Modifier les secrets plateforme (.env)",
"user_secrets:read": "Lire ses propres secrets chiffrés",
"user_secrets:write": "Ajouter, modifier, supprimer ses propres secrets"
```

Remove the old `secrets:read` / `secrets:write` descriptions. Update `scope_groups` to rename `secrets` → `platform_secrets` and add `user_secrets`.

- [ ] **Step 4: Verify**

```bash
cd backend && uv run python -c "from agflow.services.api_keys_service import ALL_SCOPES; assert 'platform_secrets:read' in ALL_SCOPES; assert 'user_secrets:write' in ALL_SCOPES; print('OK')"
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/api_keys_service.py frontend/src/components/ScopesEditor.tsx \
       frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "refactor: rename secrets scopes to platform_secrets + add user_secrets scopes"
```

---

## Task 3: Backend — vault + user_secrets schemas & service

**Files:**
- Create: `backend/src/agflow/schemas/user_secrets.py`
- Create: `backend/src/agflow/services/user_secrets_service.py`

- [ ] **Step 1: Write schemas**

```python
# backend/src/agflow/schemas/user_secrets.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VaultStatus(BaseModel):
    initialized: bool
    salt: str | None = None
    test_ciphertext: str | None = None
    test_iv: str | None = None


class VaultSetup(BaseModel):
    salt: str = Field(min_length=1)
    test_ciphertext: str = Field(min_length=1)
    test_iv: str = Field(min_length=1)


class VaultChangePassphrase(BaseModel):
    salt: str = Field(min_length=1)
    test_ciphertext: str = Field(min_length=1)
    test_iv: str = Field(min_length=1)
    re_encrypted_secrets: list[ReEncryptedSecret] = Field(default_factory=list)


class ReEncryptedSecret(BaseModel):
    id: UUID
    ciphertext: str
    iv: str


class UserSecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    ciphertext: str = Field(min_length=1)
    iv: str = Field(min_length=1)


class UserSecretSummary(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    ciphertext: str
    iv: str
    created_at: datetime
    updated_at: datetime


class UserSecretUpdate(BaseModel):
    ciphertext: str = Field(min_length=1)
    iv: str = Field(min_length=1)
```

Note: `VaultChangePassphrase` references `ReEncryptedSecret` which must be defined BEFORE it in the file. Reorder the classes so `ReEncryptedSecret` comes first.

- [ ] **Step 2: Write user_secrets service**

CRUD service for opaque blobs — the backend never validates ciphertext content:
- `get_vault_status(user_id) -> VaultStatus`
- `setup_vault(user_id, salt, test_ciphertext, test_iv) -> None`
- `change_vault_passphrase(user_id, salt, test_ciphertext, test_iv, re_encrypted: list) -> None` — transactional: updates vault columns + all secret ciphertexts in one transaction
- `list_secrets(user_id) -> list[UserSecretSummary]`
- `create_secret(user_id, name, ciphertext, iv) -> UserSecretSummary`
- `update_secret(secret_id, user_id, ciphertext, iv) -> UserSecretSummary` — verifies user_id matches
- `delete_secret(secret_id, user_id) -> None` — verifies user_id matches

Error classes: `VaultAlreadyInitializedError`, `VaultNotInitializedError`, `SecretNotFoundError`, `DuplicateSecretError`

- [ ] **Step 3: Write tests**

Tests (no DB execution — just verify imports compile):
```bash
cd backend && uv run python -c "from agflow.services.user_secrets_service import get_vault_status, setup_vault, list_secrets, create_secret; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/schemas/user_secrets.py backend/src/agflow/services/user_secrets_service.py
git commit -m "feat: user secrets service (blind blob CRUD + vault management)"
```

---

## Task 4: Backend — vault + user_secrets endpoints

**Files:**
- Create: `backend/src/agflow/api/admin/vault.py`
- Create: `backend/src/agflow/api/admin/user_secrets.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Write vault router**

Router prefix `/api/admin/vault`, auth: `require_admin` (will be changed to `require_auth` when user login exists).

Routes:
- `GET /status` → `VaultStatus` — reads vault_salt etc. from user row
- `POST /setup` → 204 — saves salt + test data, 409 if already initialized
- `POST /change-passphrase` → 204 — transactional update of vault + all secret ciphertexts

For now, get the user from JWT email → `users_service.get_by_email()`.

- [ ] **Step 2: Write user_secrets router**

Router prefix `/api/admin/user-secrets`, auth: `require_admin`.

Routes:
- `GET /` → `list[UserSecretSummary]` — only current user's secrets
- `POST /` → `UserSecretSummary` (201) — 409 on duplicate name
- `PUT /{id}` → `UserSecretSummary` — 404 if not found or wrong owner
- `DELETE /{id}` → 204

- [ ] **Step 3: Register routers in main.py**

Add imports + `app.include_router(...)` for both vault and user_secrets.

- [ ] **Step 4: Verify**

```bash
cd backend && uv run python -c "from agflow.main import create_app; app = create_app(); print('OK', len(app.routes), 'routes')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/api/admin/vault.py backend/src/agflow/api/admin/user_secrets.py \
       backend/src/agflow/main.py
git commit -m "feat: vault + user secrets admin endpoints"
```

---

## Task 5: Backend — inject user secrets at agent launch

**Files:**
- Modify: `backend/src/agflow/api/admin/containers.py` (TaskRequest model, line 20-23)
- Modify: `backend/src/agflow/services/container_runner.py` (env_list assembly, line 368-371)

- [ ] **Step 1: Add secrets field to TaskRequest**

```python
class TaskRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=16_000)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    model: str = Field(default="", max_length=100)
    secrets: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 2: Pass secrets to run_task**

In the `run_task` endpoint, pass `payload.secrets` to `container_runner.run_task()` as a new `user_secrets` parameter.

- [ ] **Step 3: Merge user secrets in container_runner**

In `run_task()`, after config is built, merge user secrets into the env list:

```python
# After config is built, before container creation:
if user_secrets:
    existing_env = config.get("Env", [])
    for k, v in user_secrets.items():
        existing_env.append(f"{k}={v}")
    config["Env"] = existing_env
```

Also update `build_run_config` signature or handle it at the `run_task` level (simpler).

- [ ] **Step 4: Verify imports**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/api/admin/containers.py backend/src/agflow/services/container_runner.py
git commit -m "feat: inject user secrets into container env at launch"
```

---

## Task 6: Frontend — WebCrypto vault library

**Files:**
- Create: `frontend/src/lib/vault.ts`

- [ ] **Step 1: Write the crypto library**

Full implementation using WebCrypto API (as specified in spec section 6.1):
- `generateSalt() → Uint8Array` (16 random bytes)
- `deriveKey(passphrase, salt) → CryptoKey` (PBKDF2, 100k iter, SHA-256 → AES-256)
- `encrypt(key, plaintext) → { ciphertext: string, iv: string }` (base64 encoded)
- `decrypt(key, ciphertext, iv) → string`
- `createTestProof(key) → { ciphertext, iv }` (encrypts "VAULT_OK")
- `verifyPassphrase(key, testCiphertext, testIv) → boolean`
- `bufferToBase64(buf) → string`
- `base64ToBuffer(b64) → Uint8Array`

- [ ] **Step 2: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/vault.ts
git commit -m "feat(frontend): WebCrypto vault lib (PBKDF2 + AES-256-GCM)"
```

---

## Task 7: Frontend — vault context + API client + hook

**Files:**
- Create: `frontend/src/hooks/useVault.ts`
- Create: `frontend/src/lib/userSecretsApi.ts`
- Create: `frontend/src/hooks/useUserSecrets.ts`

- [ ] **Step 1: Write vault context**

React context providing:
- `status: "locked" | "unlocked" | "uninitialized" | "loading"`
- `setupVault(passphrase) → Promise<void>` — generates salt, derives key, creates test proof, POSTs setup
- `unlockVault(passphrase) → Promise<boolean>` — fetches status, derives key, verifies test proof
- `lockVault()` — clears CryptoKey from memory
- `encryptSecret(plaintext) → Promise<{ciphertext, iv}>`
- `decryptSecret(ciphertext, iv) → Promise<string>`
- `isUnlocked → boolean`
- `vaultKey → CryptoKey | null` (internal, not exposed directly)

The CryptoKey is stored in a React ref (not state, not localStorage) — lost on refresh/navigation.

- [ ] **Step 2: Write API client**

```typescript
// frontend/src/lib/userSecretsApi.ts
export const vaultApi = {
  getStatus(): Promise<VaultStatus>,
  setup(payload: VaultSetup): Promise<void>,
  changePassphrase(payload: VaultChangePassphrase): Promise<void>,
};

export const userSecretsApi = {
  list(): Promise<UserSecretSummary[]>,
  create(payload: UserSecretCreate): Promise<UserSecretSummary>,
  update(id: string, payload: UserSecretUpdate): Promise<UserSecretSummary>,
  remove(id: string): Promise<void>,
};
```

- [ ] **Step 3: Write React Query hook**

```typescript
// frontend/src/hooks/useUserSecrets.ts
export function useUserSecrets() {
  // listQuery, createMutation, updateMutation, deleteMutation
  // follows useApiKeys pattern
}
```

- [ ] **Step 4: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useVault.ts frontend/src/lib/userSecretsApi.ts \
       frontend/src/hooks/useUserSecrets.ts
git commit -m "feat(frontend): vault context + user secrets API client + hook"
```

---

## Task 8: Frontend — vault dialogs

**Files:**
- Create: `frontend/src/components/VaultSetupDialog.tsx`
- Create: `frontend/src/components/VaultUnlockDialog.tsx`

- [ ] **Step 1: Write VaultSetupDialog**

Dialog for first-time passphrase creation:
- `<form>` with hidden username field (`autocomplete="username"`, value=user email)
- Password field with `autocomplete="new-password"`, `type="password"`
- Confirm password field
- Warning text: "Cette passphrase n'est stockée nulle part. Si vous l'oubliez, vos secrets seront définitivement perdus."
- Submit calls `vault.setupVault(passphrase)`
- Validation: min 8 chars, both fields match

- [ ] **Step 2: Write VaultUnlockDialog**

Dialog for session unlock:
- `<form>` with hidden username field (`autocomplete="username"`)
- Password field with `autocomplete="current-password"`, `type="password"`
- Submit calls `vault.unlockVault(passphrase)` → if false, show error "Passphrase incorrecte"
- No cancel — the dialog is mandatory to access secrets

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/VaultSetupDialog.tsx frontend/src/components/VaultUnlockDialog.tsx
git commit -m "feat(frontend): vault setup + unlock dialogs with password manager support"
```

---

## Task 9: Frontend — MySecretsPage

**Files:**
- Create: `frontend/src/pages/MySecretsPage.tsx`

- [ ] **Step 1: Write the page**

Page flow:
1. On mount, check vault status via `useVault()`
2. If `uninitialized` → show `VaultSetupDialog`
3. If `locked` → show `VaultUnlockDialog`
4. If `unlocked` → show secrets table

Table:
- Columns: Nom, Valeur (masked `sk-pr****`), Actions (reveal/edit/delete)
- 👁 button: calls `vault.decryptSecret()` and shows plaintext temporarily
- Edit: dialog with name (readonly) + new value field → re-encrypt → PUT
- Delete: ConfirmDialog
- Add: dialog with name + value → encrypt → POST

Use `PageShell` + `PageHeader` pattern. Show a lock icon + "Coffre déverrouillé" status in the header.

- [ ] **Step 2: Add i18n keys**

Add `my_secrets` section to both fr.json and en.json:
- page_title, page_subtitle, vault_locked, vault_unlocked
- setup_title, setup_warning, setup_passphrase, setup_confirm, setup_submit
- unlock_title, unlock_passphrase, unlock_submit, unlock_error
- col_name, col_value, col_actions
- add_button, reveal_button, edit_button, delete_button
- confirm_delete, add_dialog_title, edit_dialog_title
- field_name, field_value
- passphrase_min_length ("8 caractères minimum")

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/MySecretsPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): My Secrets page with vault setup/unlock + CRUD"
```

---

## Task 10: Frontend — sidebar + routes + App provider

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/main.tsx` (wrap app with VaultProvider)

- [ ] **Step 1: Add route**

```tsx
import { MySecretsPage } from "./pages/MySecretsPage";

<Route path="/my-secrets" element={<ProtectedRoute><MySecretsPage /></ProtectedRoute>} />
```

- [ ] **Step 2: Add sidebar entry**

In Sidebar.tsx, add to the platform section (or a new "Mon compte" section):
```tsx
{ to: "/my-secrets", label: t("my_secrets.page_title"), icon: Lock }
```

Import `Lock` from lucide-react.

- [ ] **Step 3: Wrap App with VaultProvider**

In `main.tsx` or `App.tsx`, wrap the app tree with `<VaultProvider>`:
```tsx
<VaultProvider>
  <App />
</VaultProvider>
```

- [ ] **Step 4: Verify + test**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/main.tsx
git commit -m "feat(frontend): /my-secrets route + sidebar + VaultProvider"
```

---

## Task 11: Deploy + Smoke Test

- [ ] **Step 1: Deploy**

```bash
./scripts/deploy.sh --rebuild
```

- [ ] **Step 2: Verify migrations**

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c \"SELECT version FROM schema_migrations WHERE version LIKE '02[67]%';\""
```
Expected: 026_user_vault, 027_user_secrets

- [ ] **Step 3: Smoke test**

1. Open `http://192.168.10.68/my-secrets`
2. See "Créez votre passphrase coffre-fort" dialog
3. Create passphrase → dialog closes, empty secrets list shown
4. Add a secret (OPENAI_API_KEY = sk-test-123) → appears in list as `sk-t****`
5. Click 👁 → value revealed
6. Refresh page → "Déverrouillez votre coffre-fort" dialog → enter passphrase → secrets visible again
7. Check DB: `SELECT name, ciphertext FROM user_secrets` → ciphertext is opaque base64, NOT "sk-test-123"

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A && git commit -m "chore: deploy user secrets zero-knowledge"
```
