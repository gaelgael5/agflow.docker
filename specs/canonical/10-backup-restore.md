# 10 — Sauvegarde et restauration

La plateforme propose **trois mécanismes complémentaires** de protection des données :

1. **Backups classiques** : `pg_dump` complets de la base PostgreSQL, planifiés ou manuels, poussés vers une ou plusieurs destinations distantes.
2. **PITR (Point-in-time Recovery)** : `pgbackrest` avec basebackups réguliers + archivage continu des WAL, permettant de cloner la base à n'importe quel instant dans une fenêtre de rétention.
3. **Git-sync de la configuration** : export sélectif de tables de configuration vers un dépôt Git, pour versionner et reproduire la config sans dumper toute la base.

Les trois cohabitent et répondent à des besoins distincts.

## 1. Backups classiques (full)

### Modèle

Un **backup full** est un snapshot complet de la base PostgreSQL, exporté en `pg_dump` gzippé. Il est :
- Stocké localement (`local_backups`) — sauf si `keep_local=false`, auquel cas le fichier local est supprimé après push.
- Optionnellement poussé vers une ou plusieurs **connexions distantes** (`remote_backup_connections`) — SFTP, S3, FTPS, ou Google Drive.

### Connexions distantes

Une connexion (`remote_backup_connections`) déclare :
- `name` : libellé humain.
- `kind` : `sftp` / `s3` / `ftps` / `gdrive`.
- `config` (JSONB) : champs spécifiques au kind (host, port, bucket, region, folder_id…).
- `credentials_ref` (référence Harpocrate) : identifiants stockés dans le coffre.
- `usage` : `full` (backup classique), `pitr` (basebackups + WAL), ou `…`.

Une connexion peut être :
- **Créée** : `POST /api/admin/backup-remotes` avec config + credentials initiaux.
- **Testée** : `POST /api/admin/backup-remotes/{id}/test` (avec creds sauvegardés) ou `POST /api/admin/backup-remotes/test` (avec creds dans le body, avant sauvegarde).
- **Testée en écriture** : `POST /api/admin/backup-remotes/{id}/test-write` qui dépose puis lit un fichier test pour valider que le compte a bien le droit d'écriture.

### Google Drive (cas spécifique)

OAuth flow dédié :
1. `GET /api/admin/backup-remotes/oauth/gdrive/redirect-uri` retourne l'URI à coller dans la Google Cloud Console.
2. `POST /api/admin/backup-remotes/oauth/gdrive/start` avec `name`, `folder_name`, `client_id`, `client_secret` → retourne `authorize_url` (popup ouvert côté frontend).
3. L'utilisateur valide chez Google → callback public `GET /api/admin/backup-remotes/oauth/gdrive/callback?state=…&code=…` qui ferme le popup et notifie l'opener.
4. Le frontend poll `GET /api/admin/backup-remotes/oauth/gdrive/session/{state}` pour récupérer le `connection_id` créé.
5. Réautorisation : `POST /api/admin/backup-remotes/{id}/reauthorize` si le refresh token est expiré.

Les tokens OAuth (access + refresh) sont stockés dans Harpocrate. La connexion stocke uniquement les refs.

### Plannings

Un **schedule full** (`backup_schedules_full`) déclare :
- `name` : libellé.
- `cron_expr` : expression cron (5 champs : minute, heure, jour-mois, mois, jour-semaine).
- `remote_connection_ids` (array) : connexions vers lesquelles pousser le backup.
- `keep_local` : booléen — conserver le fichier local après push.
- `retention_count` : nombre de backups locaux à conserver (les plus anciens sont purgés).
- `enabled` : on/off.

Endpoints : `GET / POST / PUT / DELETE /api/admin/backup-schedules/full` + `POST /run-now` + `POST /set-enabled` + `GET /history`.

### Workflow d'un backup planifié

```
Cron déclenche
  │
  ▼
pg_dump → fichier local gzippé
  │
  ├──> Insert dans local_backups (status=ok)
  │
  ▼
Pour chaque remote_connection_id :
  │
  ├──> Insert local_backup_pushes (status=pending)
  │
  ▼
Push (SFTP / S3 / FTPS / GDrive)
  │
  ├──> Update status: pushing → ok | failed
  │
  ▼
Si keep_local=false ET tous les pushes OK :
  │
  └──> Supprime le fichier local + flag local_file_present=false

Purge :
  Si len(local_backups) > retention_count :
    Supprime les plus anciens
```

### Backup manuel

`POST /api/admin/local-backups` lance immédiatement un `pg_dump` sans schedule. Pour pousser ensuite : `POST /api/admin/local-backups/{backup_id}/push-to-remote/{remote_id}`.

### Pull depuis un remote

`POST /api/admin/local-backups/pull-from-remote/{remote_id}` télécharge un fichier remote vers les backups locaux. Body : `{ "filename": "agflow_2026-05-25_03-00.sql.gz" }`.

### Restore

`POST /api/admin/local-backups/{backup_id}/restore` exécute :
1. `DROP` toutes les tables (le dump utilise `--clean --if-exists`).
2. `pg_restore` ou `psql < dump.sql.gz` selon le format.

**Destructif** : l'admin doit retaper exactement le `filename` du backup pour confirmer. Body : `{ "filename": "agflow_2026-05-25_03-00.sql.gz" }`.

Retour : `RestoreResult` avec `backup_id`, `exit_code`, `output_tail` (50 dernières lignes de la sortie de `pg_restore`).

### Scan d'historique

`POST /api/admin/local-backups/scan-schedules` parcourt les fichiers présents sur chaque remote des schedules full, reconstruit l'historique en base pour les backups qui auraient été créés hors de la plateforme (ex: après un import de remote). Retour : `{ "imported": N, "skipped": M, "errors": [...] }`.

## 2. PITR (Point-in-time Recovery)

### Modèle

PITR utilise **pgbackrest** pour combiner :
- Des **basebackups** réguliers (`full` / `diff` / `incr`).
- Un **archivage continu des WAL** (Write-Ahead Logs PostgreSQL).

Cela permet de restaurer la base à **n'importe quel instant** dans la fenêtre de rétention (typiquement les derniers jours) avec une granularité de quelques secondes.

### Configuration (singleton)

`PUT /api/admin/pitr/config` met à jour :
- `enabled` : on/off de tout le système PITR.
- `basebackup_cron` : cron pour les basebackups réguliers (typiquement quotidien).
- `basebackup_type` : `full` (toute la base), `diff` (différentiel depuis le dernier full), `incr` (incrémental depuis le précédent).
- `full_rebase_cron` : cron pour forcer un `full` (rebase) périodique afin que la chaîne diff/incr ne devienne pas trop longue.
- `retention_count` : nombre de basebackups conservés.
- `remote_connection_ids` : connexions vers lesquelles pousser les basebackups + WAL.

Le scheduler interne (`pitr_scheduler`) recharge sa config sur changement de cron / type / rebase / enabled.

### Cycle d'un basebackup

```
Cron déclenche
  │
  ▼
pgbackrest backup --type=<full|diff|incr>
  │
  ├──> Insert dans pitr_basebackups (status=running)
  │
  ▼
Backup terminé
  │
  ├──> Update status: running → ok | failed
  ├──> Update size_bytes, completed_at, pgbackrest_label
  ├──> Calcule recovery_window_start / end
  │
  ▼
Pour chaque remote_connection_id :
  │
  ├──> Insert pitr_basebackup_pushes (status=pending)
  │
  ▼
Push (rclone, aws s3 sync, etc.)
  │
  └──> Update status: pushing → ok | failed
```

### Endpoints

- `POST /api/admin/pitr/basebackups` : déclencher un basebackup manuel. Retour `202` avec `basebackup_id`.
- `GET /api/admin/pitr/basebackups` : liste les basebackups avec leur statut et leurs pushes.
- `DELETE /api/admin/pitr/basebackups/{id}` : supprimer un basebackup. **Refuse si c'est le seul restant OK** (sécurité).
- `POST /api/admin/pitr/basebackups/{id}/push/{remote_id}` : re-push manuel.
- `GET /api/admin/pitr/wal-status` : statut de l'archivage WAL (`archiving_enabled`, `last_archived_at`, `archive_lag_seconds`, `wal_disk_used_bytes`, `wal_disk_free_bytes`).
- `GET /api/admin/pitr/restore-window` : `{ "earliest": "ISO 8601", "latest": "ISO 8601" }` — fenêtre actuelle de points restaurables.

### Clones

Un **clone PITR** est une instance PostgreSQL temporaire restaurée à un instant cible (`target_time`) à partir du basebackup le plus proche + replay des WAL jusqu'au target_time.

`POST /api/admin/pitr/clones` :

```json
{ "target_time": "2026-05-25T12:34:56Z" }
```

Retour `202` : `{ "clone_id": "uuid" }`.

Le worker provisionne le clone en background :
- Démarre un container PostgreSQL temporaire isolé.
- Restaure les fichiers du basebackup.
- Replay les WAL jusqu'au target_time.
- Démarre Postgres en mode read-only.
- Démarre un container pgweb associé pour la visualisation.

Statut interrogeable via `GET /api/admin/pitr/clones/active` :

```json
{
  "id": "uuid",
  "basebackup_id": "uuid",
  "basebackup_label": "string",
  "target_time": "ISO 8601",
  "status": "restoring | ready | terminating | terminated | failed",
  "error": "string ou null",
  "pgweb_url": "https://pgweb-clone.example.com",
  "started_at": "ISO 8601",
  "ready_at": "ISO 8601 ou null",
  "expires_at": "ISO 8601",
  "expires_in_seconds": 86399
}
```

### Extension du TTL

Un clone a un TTL initial (typiquement 24 h) configurable. `POST /api/admin/pitr/clones/active/extend` ajoute 24 h. Cela évite qu'un clone d'investigation oublié monopolise les ressources éternellement.

### Terminaison

`DELETE /api/admin/pitr/clones/active` arrête les containers et efface les fichiers temporaires. Le clone passe en `terminated`.

### Limitation

**Un seul clone PITR actif à la fois** par instance d'agflow.docker. Pour étudier deux instants distincts, il faut terminer le premier clone avant d'en créer un autre.

## 3. Restore depuis un backup remote (wizard)

Cas d'usage : on n'a plus du tout la base, on veut repartir d'un backup distant qu'on a pris la précaution de pousser ailleurs.

Endpoints sous `/api/admin/restore/*`. Le frontend propose un **wizard 4 étapes** :

### Étape 1 — Sélection du coffre

`POST /api/admin/restore/vault/test` avec `{url, api_key}` valide un couple URL+key Harpocrate. Si le coffre est joignable, retourne `{ "ok": true, "secret_count": N }`.

### Étape 2 — Sélection du secret de connexion remote

`POST /api/admin/restore/vault/secrets` avec `{url, api_key, path}` liste les secrets vault sous un préfixe. L'utilisateur choisit lequel contient les credentials du remote où trouver les backups (ex: `${vault://api:remotes/sftp-backup-prod}`).

### Étape 3 — Navigation du remote

`POST /api/admin/restore/remote/browse` avec `{connection_type, manual_fields, vault_mappings, vault, path}` liste les fichiers présents sur le remote au chemin `path`. L'utilisateur navigue jusqu'au fichier de backup voulu.

### Étape 4 — Confirmation et exécution

`POST /api/admin/restore/execute` avec les mêmes champs + `file_path` lance le job de restore. Retour `202` : `{ "job_id": "uuid" }`.

Suivi : `GET /api/admin/restore/execute/{job_id}` retourne :

```json
{
  "job_id": "uuid",
  "status": "running | done | failed",
  "log": "string concaténé",
  "created_at": "ISO 8601",
  "completed_at": "ISO 8601 ou null"
}
```

Le job télécharge le fichier remote, le déchiffre si nécessaire, l'importe dans Postgres (`--clean --if-exists`).

## 4. Git-sync de la configuration

### Pourquoi

Les tables de configuration (`agents`, `roles`, `dockerfiles`, `templates`, `products`, `mcp_servers`, `discovery_services`, etc.) représentent l'**état désiré** de la plateforme. Les sauvegarder dans Git permet de :
- Versionner les changements de config.
- Reproduire un environnement de dev / staging depuis prod.
- Comparer deux états de la plateforme avec `git diff`.
- Restaurer un état antérieur précis sans toucher aux backups DB.

### Configuration (singleton)

`PUT /api/admin/git-sync/config` avec :
- `repo_url` : URL du dépôt Git (SSH ou HTTPS).
- `auth_mode` : `ssh_key` (clé privée dans Harpocrate), `pat_https` (token GitHub/GitLab), ou `basic_https` (user+password).
- `auth_secret_ref` : référence Harpocrate vers les credentials.
- `branch` : branche cible (défaut `main`).
- `commit_author_name`, `commit_author_email` : auteur des commits automatisés.
- `selected_tables` : liste des tables à exporter (ex: `["agents", "roles", "templates"]`).
- `excluded_columns` : pour chaque table, colonnes à exclure (ex: `{ "agents": ["created_at", "updated_at"] }`).
- `cron_expr` + `cron_enabled` : planification des exports automatiques.

### Tables disponibles

`GET /api/admin/git-sync/available-tables` retourne la liste des tables exportables (le sous-ensemble configuration-only de toutes les tables).

### Test de l'auth

`POST /api/admin/git-sync/test-secret-ref` avec `{auth_secret_ref}` tente un `git ls-remote` pour valider que le secret donne accès au dépôt.

### Export

`POST /api/admin/git-sync/export` exporte les `selected_tables` :
1. Clone (ou fetch) le dépôt dans un dossier temporaire.
2. Pour chaque table : lit les lignes en JSON (en excluant les `excluded_columns`), écrit `<table>.json` dans le dépôt.
3. `git add . && git commit -m "agflow auto-export <ISO>"`.
4. `git push <branch>`.
5. Retour `GitSyncExportResult` : `{ "sha": "abc123…", "tables_count": N }`.

La config est mise à jour : `last_export_at`, `last_export_status`, `last_export_sha`, `last_export_tables_count`.

### Preview import

`POST /api/admin/git-sync/preview-import` retourne ce qui serait inséré / mis à jour / supprimé sans rien faire :

```json
{
  "tables": [
    { "table": "agents", "to_insert": 2, "to_update": 5, "to_delete": 0 },
    { "table": "roles",  "to_insert": 0, "to_update": 1, "to_delete": 0 }
  ]
}
```

### Import

`POST /api/admin/git-sync/import` applique réellement :
1. Pull la branche.
2. Pour chaque `<table>.json` :
   - Compare avec l'état en base par PK.
   - Insert les nouvelles lignes.
   - Update les lignes modifiées.
   - Delete les lignes manquantes du fichier (si stratégie configurée).
3. Retour `GitSyncImportResult` : `{ "rows_inserted": N, "rows_updated": M, "rows_deleted": K }`.

### Historique

`GET /api/admin/git-sync/commits?limit=30` liste les derniers commits sur la branche, avec auteur, message, SHA, html_url (vers GitHub/GitLab).

### Limites

- Git-sync n'est **pas** une alternative à PITR ou aux backups DB : il ne sauve pas l'état runtime (sessions, agents instances, tasks, builds, runtimes…).
- Les conflits de merge sur le dépôt distant nécessitent une intervention humaine (la plateforme ne fait pas de résolution automatique).
- Pour réinitialiser complètement la plateforme depuis Git : restore DB depuis backup → import git-sync (qui complète la config).

## Quand utiliser quoi

| Besoin | Outil |
|---|---|
| Disaster recovery complet (tout perdu) | Backups full + Restore wizard |
| Récupération fine ("retour à hier 14h32") | PITR + Clone |
| Investiguer une donnée corrompue à un instant T | PITR + Clone, sans toucher la prod |
| Versionner la config (agents, roles, MCP, templates) | Git-sync |
| Cloner staging depuis prod | Backup → Restore + Git-sync |
| Audit des changements de config | `GET /api/admin/git-sync/commits` puis `git log` |
| Anti-ransomware | Backups + PITR avec pushes vers remotes immuables (S3 Object Lock, GDrive avec versions) |
