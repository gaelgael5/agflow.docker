# Spec — Secrets utilisateur zero-knowledge

> **Date** : 2026-04-12
> **Scope** : coffre-fort chiffré côté client (WebCrypto), table user_secrets, passphrase vault, UI "Mes secrets", intégration lancement agent
> **Dépend de** : spec users + API keys (2026-04-12-users-apikeys-design.md)
> **Hors scope** : migration des secrets plateforme actuels (table `secrets` existante reste inchangée), Google OAuth

---

## 1. Vue d'ensemble

### 1.1 Objectif

Chaque utilisateur dispose d'un coffre-fort personnel pour stocker ses secrets (clés API, tokens d'intégration). Le chiffrement est **zero-knowledge** : le backend ne voit jamais les valeurs en clair, seul le navigateur de l'utilisateur peut les déchiffrer via une passphrase que le backend ne connaît pas.

### 1.2 Distinction secrets plateforme vs utilisateur

| Type | Stockage | Qui gère | Chiffrement | Exemple |
|---|---|---|---|---|
| **Plateforme** | `.env` sur le host LXC | Admin uniquement | Aucun (fichier host) | `JWT_SECRET`, `ANTHROPIC_API_KEY` platform |
| **Utilisateur** | Table `user_secrets` en DB | Chaque user pour les siens | AES-256-GCM côté client | `OPENAI_API_KEY` perso, `GITHUB_TOKEN` |

Les secrets plateforme (`.env`) restent gérés par le Module M0 existant (table `secrets` + pgcrypto). Aucune modification à cette table.

### 1.3 Propriétés de sécurité

- Le **backend ne voit JAMAIS** : la passphrase, la clé dérivée, ni les valeurs des secrets
- La passphrase **ne transite JAMAIS** par le backend — vérification côté client via test ciphertext
- L'admin avec accès DB + source code **ne peut PAS** déchiffrer les secrets utilisateur
- Passphrase oubliée = **secrets perdus** (irrecoverable by design)
- Exception : au **lancement d'un agent**, le frontend envoie les plaintext nécessaires au backend via HTTPS pour injection dans le container. Le backend ne les stocke pas — transient en RAM uniquement.

---

## 2. Cryptographie

### 2.1 Algorithmes

| Opération | Algorithme | Paramètres |
|---|---|---|
| Dérivation de clé | PBKDF2 | Salt 16 bytes, 100 000 itérations, SHA-256 |
| Chiffrement | AES-256-GCM | IV 12 bytes random par secret, tag 128 bits (inclus dans ciphertext WebCrypto) |
| Vérification passphrase | Encryption test | Chiffre "VAULT_OK", stocke le ciphertext. Déchiffrement réussi = bonne passphrase |

### 2.2 Flows

**Création du coffre (première fois)** :
```
1. User saisit passphrase + confirmation
2. Frontend : salt = crypto.getRandomValues(16 bytes)
3. Frontend : key = PBKDF2(passphrase, salt, 100k, SHA-256) → AES-256 CryptoKey
4. Frontend : { test_ciphertext, test_iv } = AES-GCM(key, "VAULT_OK")
5. → POST /api/admin/vault/setup { salt: base64, test_ciphertext: base64, test_iv: base64 }
6. Backend stocke salt + test_ciphertext + test_iv sur le user row
```

**Déverrouillage (chaque session)** :
```
1. User saisit passphrase
2. → GET /api/admin/vault/status → { salt, test_ciphertext, test_iv }
3. Frontend : key = PBKDF2(passphrase, salt, 100k)
4. Frontend : decrypt(key, test_ciphertext, test_iv) → "VAULT_OK" ? → déverrouillé ✅
5. CryptoKey gardée en mémoire JS (variable, pas localStorage)
6. Perdue au refresh / logout / fermeture onglet
```

**Ajout d'un secret** :
```
1. Frontend : { ciphertext, iv } = AES-GCM(key, plaintext)
2. → POST /api/admin/user-secrets { name: "OPENAI_API_KEY", ciphertext: base64, iv: base64 }
3. Backend stocke le blob opaque. Ne voit jamais le plaintext.
```

**Lecture des secrets** :
```
1. → GET /api/admin/user-secrets → [{ id, name, ciphertext, iv, created_at, updated_at }]
2. Frontend : pour chaque → decrypt(key, ciphertext, iv) → plaintext
3. Affichage : valeur masquée avec option "révéler"
```

**Lancement d'un agent** :
```
1. Frontend déchiffre localement les secrets requis par les Params du Dockerfile
2. → POST /api/admin/dockerfiles/{id}/task {
     instruction: "...",
     secrets: { "OPENAI_API_KEY": "sk-proj-abc..." }  ← plaintext via HTTPS
   }
3. Backend reçoit les plaintext, les injecte dans le container comme env vars
4. Le backend NE STOCKE PAS les plaintext — transient en RAM
```

---

## 3. Modèle de données

### 3.1 Colonnes ajoutées à `users`

```sql
-- Migration 026_user_vault.sql
ALTER TABLE users ADD COLUMN vault_salt TEXT;
ALTER TABLE users ADD COLUMN vault_test_ciphertext TEXT;
ALTER TABLE users ADD COLUMN vault_test_iv TEXT;
```

- `vault_salt = NULL` → le user n'a pas encore créé sa passphrase
- `vault_salt IS NOT NULL` → coffre initialisé

### 3.2 Table `user_secrets`

```sql
-- Migration 027_user_secrets.sql
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

### 3.3 Contenu des colonnes

| Colonne | Contenu | L'admin voit ? | Peut déchiffrer ? |
|---|---|---|---|
| `users.vault_salt` | Base64(16 bytes random) | ✅ | Inutile sans passphrase |
| `users.vault_test_ciphertext` | Base64(AES-GCM("VAULT_OK")) | ✅ | ❌ |
| `users.vault_test_iv` | Base64(12 bytes) | ✅ | Inutile sans clé |
| `user_secrets.ciphertext` | Base64(AES-GCM(plaintext)) | ✅ | ❌ |
| `user_secrets.iv` | Base64(12 bytes) | ✅ | Inutile sans clé |

---

## 4. Scopes

### 4.1 Nouveaux scopes

| Scope | Remplace | Description |
|---|---|---|
| `platform_secrets:read` | `secrets:read` | Lire les noms des secrets plateforme (admin only) |
| `platform_secrets:write` | `secrets:write` | Modifier les secrets plateforme (admin only) |
| `user_secrets:read` | — (nouveau) | Lire ses propres secrets chiffrés |
| `user_secrets:write` | — (nouveau) | Ajouter/modifier/supprimer ses propres secrets |

### 4.2 Impact sur le catalogue ALL_SCOPES

Remplacer `secrets:read` / `secrets:write` par `platform_secrets:read` / `platform_secrets:write`.
Ajouter `user_secrets:read` / `user_secrets:write`.

### 4.3 Impact sur la page Secrets existante (Module M0)

La page actuelle `/secrets` (SecretsPage.tsx) gère les secrets **plateforme** (pgcrypto). Elle reste inchangée, mais son scope passe de `secrets:*` à `platform_secrets:*`. Les users sans ce scope ne la voient pas dans la sidebar.

---

## 5. Endpoints backend

### 5.1 Vault management

Préfixe : `/api/admin/vault`
Auth : JWT (session)

| Méthode | Route | Description | Body |
|---|---|---|---|
| `GET` | `/vault/status` | Retourne si le vault est initialisé + salt + test data | — |
| `POST` | `/vault/setup` | Initialise le coffre (première fois) | `{ salt, test_ciphertext, test_iv }` |
| `POST` | `/vault/change-passphrase` | Change la passphrase (re-chiffre le test + tous les secrets) | `{ salt, test_ciphertext, test_iv, re_encrypted_secrets: [{id, ciphertext, iv}] }` |

**`GET /vault/status` response** :
```json
{
  "initialized": true,
  "salt": "base64...",
  "test_ciphertext": "base64...",
  "test_iv": "base64..."
}
```
Si `initialized: false`, le frontend affiche le dialog de création.

### 5.2 User secrets CRUD

Préfixe : `/api/admin/user-secrets`
Auth : JWT (session)

| Méthode | Route | Description | Body |
|---|---|---|---|
| `GET` | `/user-secrets` | Liste tous les secrets du user connecté | — |
| `POST` | `/user-secrets` | Ajouter un secret | `{ name, ciphertext, iv }` |
| `PUT` | `/user-secrets/{id}` | Modifier un secret | `{ ciphertext, iv }` |
| `DELETE` | `/user-secrets/{id}` | Supprimer un secret | — |

**Le backend ne valide PAS le contenu du ciphertext** — c'est un blob opaque. Il vérifie seulement :
- Le user est authentifié
- Le secret appartient au user (`user_id` match)
- Le nom est unique par user

### 5.3 Modification du lancement agent

L'endpoint `POST /api/admin/dockerfiles/{id}/task` accepte un champ optionnel `secrets`:
```json
{
  "instruction": "...",
  "secrets": {
    "OPENAI_API_KEY": "sk-proj-abc...",
    "GITHUB_TOKEN": "ghp_xxx..."
  }
}
```

Le backend merge ces secrets dans les env vars du container (en plus des Environments du Dockerfile.json). Les secrets user **écrasent** les valeurs par défaut.

---

## 6. Frontend — lib crypto

### 6.1 Fichier `frontend/src/lib/vault.ts`

```typescript
// Salt generation
export function generateSalt(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(16));
}

// Key derivation
export async function deriveKey(
  passphrase: string,
  salt: Uint8Array,
): Promise<CryptoKey> {
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

// Encrypt plaintext → { ciphertext, iv } as base64 strings
export async function encrypt(
  key: CryptoKey,
  plaintext: string,
): Promise<{ ciphertext: string; iv: string }> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encoded = new TextEncoder().encode(plaintext);
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    key,
    encoded,
  );
  return {
    ciphertext: bufferToBase64(encrypted),
    iv: bufferToBase64(iv),
  };
}

// Decrypt base64 ciphertext → plaintext string
export async function decrypt(
  key: CryptoKey,
  ciphertext: string,
  iv: string,
): Promise<string> {
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: base64ToBuffer(iv) },
    key,
    base64ToBuffer(ciphertext),
  );
  return new TextDecoder().decode(decrypted);
}

// Test proof for passphrase verification
const VAULT_TEST_PLAINTEXT = "VAULT_OK";

export async function createTestProof(
  key: CryptoKey,
): Promise<{ ciphertext: string; iv: string }> {
  return encrypt(key, VAULT_TEST_PLAINTEXT);
}

export async function verifyPassphrase(
  key: CryptoKey,
  testCiphertext: string,
  testIv: string,
): Promise<boolean> {
  try {
    const result = await decrypt(key, testCiphertext, testIv);
    return result === VAULT_TEST_PLAINTEXT;
  } catch {
    return false;
  }
}

// Helpers
function bufferToBase64(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

function base64ToBuffer(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
```

### 6.2 Vault state management

Nouveau fichier `frontend/src/hooks/useVault.ts` — React context + hook :
- `VaultProvider` wraps the app
- State : `{ status: "locked" | "unlocked" | "uninitialized", key: CryptoKey | null }`
- `setupVault(passphrase)` — creates vault, derives key, POSTs setup
- `unlockVault(passphrase)` — derives key, verifies test proof, stores key in memory
- `lockVault()` — clears key from memory
- `encryptSecret(plaintext)` → `{ ciphertext, iv }`
- `decryptSecret(ciphertext, iv)` → plaintext
- `isUnlocked()` → boolean

---

## 7. Frontend — UI

### 7.1 Dialog de création de passphrase

Affiché automatiquement quand un user accède à "Mes secrets" et `vault_salt = NULL`.

```html
<form>
  <input type="hidden" name="username" autocomplete="username" value="{user.email}" />
  
  <label>Passphrase coffre-fort</label>
  <input type="password" name="password" autocomplete="new-password" />
  
  <label>Confirmer la passphrase</label>
  <input type="password" autocomplete="new-password" />
  
  <p class="warning">⚠️ Cette passphrase n'est stockée nulle part.
  Si vous l'oubliez, vos secrets seront définitivement perdus.</p>
  
  <button type="submit">Créer le coffre-fort</button>
</form>
```

`autocomplete="new-password"` → les gestionnaires de mots de passe (1Password, Bitwarden, navigateur) proposeront de sauvegarder.

### 7.2 Dialog de déverrouillage

Affiché quand le vault est initialisé mais pas déverrouillé dans la session courante.

```html
<form>
  <input type="hidden" name="username" autocomplete="username" value="{user.email}" />
  
  <label>Passphrase coffre-fort</label>
  <input type="password" name="password" autocomplete="current-password" />
  
  <button type="submit">Déverrouiller</button>
</form>
```

`autocomplete="current-password"` → les gestionnaires proposent le mot de passe sauvegardé.

### 7.3 Page "Mes secrets"

Nouvelle page `/my-secrets` dans la sidebar (section "Mon compte" ou en haut de "Plateforme").

```
┌─────────────────────────────────────────────────────────┐
│ 🔐 Mes secrets                                         │
│ Vos secrets sont chiffrés de bout en bout.              │
│ Seule votre passphrase peut les déchiffrer.             │
├────────────────────┬─────────────────┬──────┬───────────┤
│ Nom                │ Valeur          │      │ Actions   │
├────────────────────┼─────────────────┼──────┼───────────┤
│ OPENAI_API_KEY     │ sk-pro****      │ 👁   │ ✏️ 🗑     │
│ GITHUB_TOKEN       │ ghp_xx****      │ 👁   │ ✏️ 🗑     │
├────────────────────┴─────────────────┴──────┴───────────┤
│ + Ajouter un secret                                     │
└─────────────────────────────────────────────────────────┘
```

- Valeurs masquées par défaut (4 premiers chars + `****`)
- Bouton 👁 pour révéler temporairement (déchiffre à la volée)
- Edit = re-chiffre avec la même clé
- Delete = suppression en DB (pas de soft delete)

---

## 8. Fichiers à créer / modifier

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `backend/migrations/026_user_vault.sql` | ALTER users + 3 colonnes vault |
| `backend/migrations/027_user_secrets.sql` | Table user_secrets |
| `backend/src/agflow/schemas/user_secrets.py` | DTOs Pydantic |
| `backend/src/agflow/services/user_secrets_service.py` | CRUD blob opaque |
| `backend/src/agflow/api/admin/vault.py` | Router vault (setup, status, change) |
| `backend/src/agflow/api/admin/user_secrets.py` | Router user secrets CRUD |
| `frontend/src/lib/vault.ts` | WebCrypto: derive, encrypt, decrypt, verify |
| `frontend/src/hooks/useVault.ts` | React context + hook (lock/unlock state) |
| `frontend/src/lib/userSecretsApi.ts` | API client |
| `frontend/src/hooks/useUserSecrets.ts` | React Query hook |
| `frontend/src/pages/MySecretsPage.tsx` | Page "Mes secrets" |
| `frontend/src/components/VaultSetupDialog.tsx` | Dialog création passphrase |
| `frontend/src/components/VaultUnlockDialog.tsx` | Dialog déverrouillage |

### Fichiers modifiés

| Fichier | Modification |
|---|---|
| `backend/src/agflow/main.py` | Register vault + user_secrets routers |
| `backend/src/agflow/services/api_keys_service.py` | Rename `secrets:*` → `platform_secrets:*` dans ALL_SCOPES, ajouter `user_secrets:*` |
| `backend/src/agflow/api/admin/containers.py` | Accepter `secrets` dans TaskRequest pour injection au lancement |
| `backend/src/agflow/services/container_runner.py` | Merger user secrets dans les env vars du container |
| `frontend/src/App.tsx` | Route `/my-secrets` |
| `frontend/src/components/layout/Sidebar.tsx` | Entrée "Mes secrets" |
| `frontend/src/components/ScopesEditor.tsx` | Rename secrets scopes + ajouter user_secrets |
| `frontend/src/i18n/fr.json` | Clés i18n vault + secrets |
| `frontend/src/i18n/en.json` | Idem anglais |

---

## 9. Tests

### Backend

| Test | Vérifie |
|---|---|
| `test_vault_setup` | POST setup stocke salt + test ciphertext |
| `test_vault_status_uninitialized` | GET status → initialized: false quand vault_salt NULL |
| `test_vault_status_initialized` | GET status → initialized: true + retourne salt + test data |
| `test_create_user_secret` | POST stocke ciphertext opaque |
| `test_list_user_secrets` | GET retourne uniquement les secrets du user connecté |
| `test_update_user_secret` | PUT remplace le ciphertext |
| `test_delete_user_secret` | DELETE supprime |
| `test_user_cannot_see_other_user_secrets` | User A ne voit pas les secrets de User B |
| `test_task_with_secrets` | POST /task avec secrets injecte dans le container |

### Frontend

| Test | Vérifie |
|---|---|
| `test_vault_derive_encrypt_decrypt_roundtrip` | WebCrypto: plaintext → encrypt → decrypt → même plaintext |
| `test_vault_wrong_passphrase_fails` | Mauvaise passphrase → verifyPassphrase retourne false |
| `test_my_secrets_page_renders` | Page affiche la liste des secrets |

---

## 10. Hors scope

| Sujet | Raison |
|---|---|
| Changement de la table `secrets` existante (M0) | Reste pour les secrets plateforme, pas touché |
| Recovery de passphrase | Zero-knowledge = pas de recovery by design |
| Partage de secrets entre users | Pas prévu, chaque user a son coffre isolé |
| Chiffrement des secrets plateforme côté client | L'admin gère le .env, pas de zero-knowledge côté admin |
| Synchronisation multi-device de la passphrase | Les gestionnaires de mots de passe s'en chargent (d'où autocomplete) |
