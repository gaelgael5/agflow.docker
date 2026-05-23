# Restore Wizard — Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Page dédiée de restauration guidée permettant, sur une machine fraîchement installée, de se connecter à un vault Harpocrate, résoudre les credentials d'une connexion distante, naviguer les fichiers, sélectionner un backup et le restaurer — sans aucune configuration préalable dans la base.

**Architecture:** Wizard en 4 étapes séquentielles, état complet en React state (aucune persistence). 4 endpoints backend stateless (aucune écriture DB). Les credentials vault sont passés à chaque appel API. Les providers de connexion existants (sftp_provider.py, etc.) sont réutilisés avec injection de credentials résolus depuis le vault.

**Tech Stack:** FastAPI + asyncpg + structlog / React 18 + TypeScript strict + TanStack Query + Tailwind + shadcn/ui + i18next

---

## 1. Routing & navigation

- Nouvelle page `frontend/src/pages/RestorePage.tsx`
- Route `/restore` ajoutée dans le router
- Entrée dans la sidebar admin (icône `RotateCcw`, label i18n `restore.nav_label`)
- Pas de lien depuis `BackupsPage` — la page est autonome

---

## 2. Flux utilisateur — 4 étapes séquentielles

Chaque étape est verrouillée tant que la précédente n'est pas validée. L'étape active est mise en évidence, les étapes complétées affichent un indicateur vert.

### Étape 1 — Connexion vault

L'utilisateur saisit :
- **URL du vault** (ex : `https://vault.yoops.org`)
- **API key**

Action : `POST /api/admin/restore/vault/test` — si 200, étape marquée ✓ et secrets chargés en cache.

### Étape 2 — Connexion distante

**2a — Choix du type :** `SFTP | S3 | FTPS | GDrive`

**2b — Formulaire dynamique** selon le type. Chaque champ est soit :
- **Saisie libre** (non-sensible : host, port, bucket, path, region)
- **Vault picker** (sensible : password, clé privée, access key, etc.) — liste déroulante affichant `nom (tags)` pour chaque secret disponible dans le vault

Champs par type :

| Type | Saisie libre | Vault picker |
|------|-------------|-------------|
| SFTP | host, port (déf. 22), remote_path | username, password *(opt)*, private_key *(opt)*, passphrase *(opt)* |
| S3 | bucket, region, prefix | access_key_id, secret_access_key |
| FTPS | host, port (déf. 21), remote_path | username, password |
| GDrive | — | credentials_json |

Pour SFTP, les secrets de type clé privée sont filtrés depuis le path `certificates` du vault ; les autres (username, password) depuis le path `remote-backups`.

Action : bouton "Tester la connexion" → `POST /api/admin/restore/remote/browse` avec `path="/"` pour valider les credentials. Si 200, étape marquée ✓.

### Étape 3 — Navigateur de fichiers distant

Composant `RemoteFileBrowser` :
- Affiche le contenu du répertoire courant (nom, taille, date)
- Clic sur dossier → navigation (nouvel appel `POST /api/admin/restore/remote/browse` avec le path cible)
- Fil d'Ariane cliquable pour remonter
- Fichiers `.dump` et `.sql` mis en évidence (badge + curseur pointer)
- Clic sur un fichier backup → le sélectionne, active l'étape 4

### Étape 4 — Confirmation et restauration

Résumé : vault URL, type connexion, fichier sélectionné (nom + taille).

Bouton **Restaurer** → `POST /api/admin/restore/execute` → réponse `202 { job_id }`.

Suivi de progression via polling `GET /api/admin/restore/execute/{job_id}` (intervalle 2 s) jusqu'à statut `done` ou `failed`.

Affichage : barre de progression + logs en temps réel (texte brut depuis le job).

En cas d'erreur : message explicite + bouton "Recommencer depuis l'étape 2".

---

## 3. Backend — 4 endpoints stateless

Tous sous le router `/api/admin/restore/`. Aucune écriture en base sauf la table `restore_jobs` (id, status, log, created_at).

Les credentials vault sont transmis via headers `X-Vault-Url` et `X-Vault-Api-Key` sur tous les appels sauf le test initial.

### 3a. `POST /api/admin/restore/vault/test`

```python
class VaultTestRequest(BaseModel):
    url: str
    api_key: str

# Retourne 200 {} si connexion OK, 401 si clé invalide, 503 si injoignable
```

### 3b. `GET /api/admin/restore/vault/secrets`

Headers : `X-Vault-Url`, `X-Vault-Api-Key`  
Query param : `path` (ex: `certificates`, `remote-backups`)

```python
class VaultSecretItem(BaseModel):
    name: str
    tags: list[str]
    kind: str  # "certificate" | "secret"
```

### 3c. `POST /api/admin/restore/remote/browse`

```python
class RemoteBrowseRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]       # host, port, path, bucket, region...
    vault_mappings: dict[str, str]      # field_name → vault secret name
    vault: VaultRef                     # url + api_key

class RemoteFileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: datetime | None
```

Le backend résout les `vault_mappings` en appelant l'API Harpocrate, puis instancie le provider existant (`SftpProvider`, `S3Provider`, etc.) avec les credentials résolus.

### 3d. `POST /api/admin/restore/execute`

```python
class RestoreExecuteRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]
    vault: VaultRef
    file_path: str                      # chemin complet du fichier backup sur le remote

# Retourne 202 { job_id: UUID }
```

Exécution asynchrone (asyncio task) :
1. Résolution credentials depuis vault
2. Téléchargement du fichier via provider → fichier temporaire local
3. `pg_restore` ou `psql` selon extension (`.dump` → pg_restore, `.sql` → psql)
4. Suppression fichier temporaire
5. Mise à jour `restore_jobs` (status, log)

### 3e. `GET /api/admin/restore/execute/{job_id}`

```python
class RestoreJobStatus(BaseModel):
    job_id: UUID
    status: Literal["running", "done", "failed"]
    log: str
    created_at: datetime
    completed_at: datetime | None
```

---

## 4. Composants frontend

```
frontend/src/pages/RestorePage.tsx          # page principale + state wizard
frontend/src/components/restore/
  VaultConnectStep.tsx                      # étape 1
  RemoteConnectionStep.tsx                  # étape 2 (form dynamique)
  VaultSecretPicker.tsx                     # select avec tags, réutilisable
  RemoteFileBrowser.tsx                     # étape 3 (navigateur)
  RestoreConfirmStep.tsx                    # étape 4 (confirm + progress)
  RestoreTimelineItem.tsx                   # wrapper visuel étape (numero, titre, état)
```

**State dans `RestorePage` :**

```typescript
interface RestoreWizardState {
  step: 1 | 2 | 3 | 4;
  vault: { url: string; apiKey: string } | null;
  secrets: VaultSecretItem[];
  connectionType: "sftp" | "s3" | "ftps" | "gdrive" | null;
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;   // field → secret name
  selectedFile: { path: string; name: string; size_bytes: number } | null;
  jobId: string | null;
}
```

---

## 5. Migration DB

Une seule nouvelle table :

```sql
CREATE TABLE restore_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status      TEXT NOT NULL DEFAULT 'running',  -- running | done | failed
    log         TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
```

Pas de FK — les jobs sont éphémères. Pas de nettoyage automatique dans ce chantier.

---

## 6. i18n

Toutes les clés sous le namespace `restore.*`. Langues : `fr` et `en`.

Clés principales : `restore.nav_label`, `restore.page_title`, `restore.step_vault`, `restore.step_connection`, `restore.step_browse`, `restore.step_confirm`, `restore.btn_test`, `restore.btn_browse`, `restore.btn_restore`, `restore.status_running`, `restore.status_done`, `restore.status_failed`.

---

## 7. Ce qui est hors scope

- Nettoyage automatique des `restore_jobs` anciens
- Support GDrive OAuth dans le wizard (les credentials GDrive doivent déjà être dans le vault sous forme de JSON)
- Restauration PITR (point-in-time) — uniquement pg_dump/pg_restore ici
- Historique des restaurations
