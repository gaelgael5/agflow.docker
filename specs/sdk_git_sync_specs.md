# SPECS — SDK Git Sync
**Version** : 1.0  
**Statut** : Cadrage finalisé — prêt pour développement  
**Scope** : SDK générique, développé une fois, copié sur tous les modules ag.flow

---

## 1. Contexte et positionnement

### Objectif

Le SDK Git Sync permet à chaque module ag.flow d'exporter un snapshot de ses données de configuration vers un repo Git privé, et de le réimporter sur une autre instance. Il ne remplace pas les backups PostgreSQL natifs — ceux-ci restent gérés par PostgreSQL. Le SDK couvre uniquement le transfert de données de configuration entre instances.

### Cas d'usage nominal

```
Instance PROD
  └── Export → git/<module>/datas/     ← snapshot versionné

Instance STAGING (nouvelle)
  └── Import ← git/<module>/datas/     ← rejeu de la conf PROD
```

Le versioning est assuré nativement par Git. Chaque export est un commit. L'historique complet est disponible via Git standard.

### Principe de déploiement

Le SDK est un répertoire autonome sans dépendance aux modèles métier du module consommateur. Il est copié tel quel dans chaque module. Seul le SDK Harpocrate (résolution des secrets) est une dépendance externe.

```
<module>/
  sdk/
    git_sync/     ← ce SDK
    vault/        ← SDK Harpocrate (dépendance)
```

---

## 2. Structure des fichiers

```
sdk/
  git_sync/
    __init__.py
    models.py
    exceptions.py
    dependency_resolver.py
    git_service.py
    export_service.py
    import_service.py
    auth/
      __init__.py
      base.py
      ssh_key.py
      pat_https.py
      basic_https.py
      factory.py
```

---

## 3. Models (`models.py`)

### `AuthMode` (Enum)

| Valeur | Description |
|--------|-------------|
| `ssh_key` | Clé privée SSH (stockée dans Harpocrate) |
| `pat_https` | Personal Access Token HTTPS |
| `basic_https` | Username + password HTTPS |

### `GitConfig`

| Champ | Type | Description |
|-------|------|-------------|
| `repo_url` | `str` | URL du repo. `git@github.com:org/repo.git` ou `https://github.com/org/repo.git` |
| `auth_mode` | `AuthMode` | Mode d'authentification |
| `auth_secret_ref` | `str` | Référence Harpocrate `${vault://git/docker/ssh_key}` ou valeur directe (dev/test) |
| `branch` | `str` | Branche cible. Défaut : `"main"` |
| `module_name` | `str` | Nom du module : `"docker"`, `"workflow"`, etc. |
| `commit_author_name` | `str` | Nom auteur des commits |
| `commit_author_email` | `str` | Email auteur des commits |
| `target_commit` | `Optional[str]` | SHA de commit pour import depuis un état historique. Si `None` → HEAD |
| `excluded_columns` | `Dict[str, List[str]]` | Colonnes exclues de l'export/import par table. Clé : `"public.stacks"`. Défaut : `{}` |

**Remarque sur `auth_secret_ref`** : si la valeur commence par `${vault://`, le SDK résout via Harpocrate. Sinon la valeur est utilisée directement (mode dev/test uniquement).

**Remarque sur `excluded_columns`** : le SDK exclut toujours automatiquement les colonnes `GENERATED ALWAYS` et les colonnes identity `GENERATED ALWAYS`, indépendamment de cette configuration.

### `TableRef`

| Champ | Type | Description |
|-------|------|-------------|
| `schema` | `str` | Schéma PostgreSQL. Ex : `"public"` |
| `table` | `str` | Nom de la table. Ex : `"stacks"` |
| `full_name` | `str` (property) | `"public.stacks"` |
| `csv_name` | `str` (property) | `"public.stacks.csv"` |
| `tmp_name` | `str` (property) | `"tmp_public_stacks"` |

### `DependencyGraph`

| Champ | Type | Description |
|-------|------|-------------|
| `tables` | `List[TableRef]` | Toutes les tables du graphe |
| `edges` | `List[Tuple[TableRef, TableRef]]` | `(dependent, depends_on)` |
| `ordered` | `List[TableRef]` (property) | Tri topologique — ordre d'import |
| `ordered_reverse` | `List[TableRef]` (property) | Ordre inverse — pour les suppressions et DROP |

### `TablePreview`

| Champ | Type | Description |
|-------|------|-------------|
| `table` | `TableRef` | Table concernée |
| `to_insert` | `int` | Lignes à insérer |
| `to_update` | `int` | Lignes à modifier |
| `to_delete` | `int` | Lignes à supprimer |

### `ImportPreview`

| Champ | Type | Description |
|-------|------|-------------|
| `tables` | `List[TablePreview]` | Détail par table |

### `SyncResult`

| Champ | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Résultat global |
| `commit_sha` | `Optional[str]` | SHA du commit produit. `None` si rien à committer |
| `tables_exported` | `List[TableRef]` | Tables effectivement exportées |
| `errors` | `List[str]` | Erreurs non bloquantes |

### `ImportResult`

| Champ | Type | Description |
|-------|------|-------------|
| `success` | `bool` | Résultat global |
| `tables_processed` | `List[TableRef]` | Tables traitées |
| `rows_inserted` | `Dict[str, int]` | Clé : `table.full_name` |
| `rows_updated` | `Dict[str, int]` | Clé : `table.full_name` |
| `rows_deleted` | `Dict[str, int]` | Clé : `table.full_name` |
| `errors` | `List[str]` | Erreurs non bloquantes |

---

## 4. Exceptions (`exceptions.py`)

| Exception | Hérite de | Déclenchée quand |
|-----------|-----------|-----------------|
| `GitSyncError` | `Exception` | Base de toutes les exceptions du SDK |
| `GitAuthError` | `GitSyncError` | Clé invalide, token expiré, accès refusé |
| `GitCloneError` | `GitSyncError` | Échec du clone (réseau, URL incorrecte) |
| `GitPushError` | `GitSyncError` | Échec du push |
| `GitConflictError` | `GitSyncError` | `--ff-only` échoue — conflit détecté |
| `GitDirtyRepoError` | `GitSyncError` | Répertoire temporaire dans un état inattendu |
| `DependencyResolveError` | `GitSyncError` | Cycle détecté dans le graphe FK |
| `ImportConflictError` | `GitSyncError` | Erreur lors du MERGE PostgreSQL |
| `TableNotFoundError` | `GitSyncError` | Table référencée dans CSV introuvable en base |
| `VaultResolutionError` | `GitSyncError` | Échec de résolution du secret Harpocrate |

---

## 5. Couche Auth

### `base.py` — `GitAuthProvider` (ABC)

Interface commune à toutes les implémentations.

```
setup() -> None
  Préparation avant usage.
  SSH : écriture de la clé dans un fichier temporaire, chmod 600.
  HTTPS : no-op.

teardown() -> None
  Nettoyage après usage.
  SSH : suppression du fichier temporaire.
  HTTPS : no-op.
  TOUJOURS appelé dans un finally.

get_clone_url(repo_url: str) -> str
  SSH  : retourne repo_url inchangée.
  HTTPS : injecte les credentials dans l'URL.

get_env() -> dict
  SSH  : {"GIT_SSH_COMMAND": "ssh -i <key_path> -o StrictHostKeyChecking=no"}
  HTTPS : {}
```

### `ssh_key.py` — `SSHKeyAuthProvider`

- Reçoit : clé privée PEM (str)
- `setup()` : écrit la clé via `tempfile.mkstemp`, applique `chmod 600`, stocke le path dans `self.key_path`
- `get_env()` : retourne `GIT_SSH_COMMAND` avec `-i self.key_path`
- `teardown()` : supprime le fichier temporaire
- `get_clone_url()` : retourne `repo_url` inchangée

### `pat_https.py` — `PATHttpsAuthProvider`

- Reçoit : token (str)
- `get_clone_url()` : transforme `https://github.com/...` en `https://<token>@github.com/...`. Nettoie les credentials déjà présents avant injection.
- `get_env()`, `setup()`, `teardown()` : no-op

### `basic_https.py` — `BasicHttpsAuthProvider`

- Reçoit : JSON `{"username": "...", "password": "..."}`
- `get_clone_url()` : injecte `https://<username>:<password>@...`
- `get_env()`, `setup()`, `teardown()` : no-op

### `factory.py` — `GitAuthProviderFactory`

```
async build(config: GitConfig, vault_client: HarpocrateClient) -> GitAuthProvider

  1. Résolution du secret :
       Si config.auth_secret_ref commence par "${vault://"
         → secret = await vault_client.resolve(config.auth_secret_ref)
         → Lance VaultResolutionError si échec
       Sinon
         → secret = config.auth_secret_ref  (mode dev/test)

  2. Sélection du provider selon config.auth_mode :
       AuthMode.SSH_KEY     → SSHKeyAuthProvider(secret)
       AuthMode.PAT_HTTPS   → PATHttpsAuthProvider(secret)
       AuthMode.BASIC_HTTPS → BasicHttpsAuthProvider(secret)
         (pour BASIC_HTTPS, secret est un JSON {"username":..., "password":...})

  3. Retourne l'instance
```

---

## 6. `GitService` (`git_service.py`)

Responsabilité unique : toutes les opérations Git via subprocess. Ne connaît pas PostgreSQL.

### Constructeur

```
__init__(config: GitConfig, vault_client: HarpocrateClient)
  - Stocke config et vault_client
  - Ne résout pas le secret à ce stade (résolution lazy au premier clone)
```

### Méthodes

```
async clone() -> Path
  - Résout auth via GitAuthProviderFactory.build()
  - auth_provider.setup()
  - Crée un répertoire temporaire via tempfile.mkdtemp()
  - git clone --branch <config.branch> --depth 1 <clone_url> <tmp_dir>
    avec env injecté depuis auth_provider.get_env()
  - Si config.target_commit est défini :
      git -C <tmp_dir> checkout <config.target_commit>
  - Stocke auth_provider dans self._auth_provider pour teardown
  - Retourne Path(tmp_dir)
  - Lance GitCloneError si échec subprocess

get_module_path(repo_root: Path) -> Path
  - Retourne repo_root / config.module_name / "datas"
  - Crée les répertoires manquants (mkdir -p)

async pull_ff_only(repo_root: Path) -> None
  - git -C <repo_root> pull --ff-only
  - Lance GitConflictError si code retour != 0
    avec message : "Le repo a été modifié depuis le dernier export.
                    Exportez à nouveau ou résolvez manuellement."

async commit_and_push(repo_root: Path, message: str) -> Optional[str]
  - git -C <repo_root> config user.name  <config.commit_author_name>
  - git -C <repo_root> config user.email <config.commit_author_email>
  - git -C <repo_root> add <module_path>
  - git -C <repo_root> diff --cached --quiet
      → Si rien à committer : retourne None sans erreur ni exception
  - git -C <repo_root> commit -m "<message>"
  - git -C <repo_root> push origin <config.branch>
  - Retourne git -C <repo_root> rev-parse HEAD
  - Lance GitPushError si push échoue

cleanup(repo_root: Path) -> None
  - shutil.rmtree(repo_root, ignore_errors=True)
  - self._auth_provider.teardown() si auth_provider initialisé
  - TOUJOURS appelé dans un finally
```

### Pattern d'usage imposé

```python
repo_root = None
try:
    repo_root = await git_service.clone()
    # ... travail ...
    sha = await git_service.commit_and_push(repo_root, message)
finally:
    if repo_root:
        git_service.cleanup(repo_root)
```

---

## 7. `DependencyResolver` (`dependency_resolver.py`)

Responsabilité : interroger PostgreSQL pour extraire le graphe FK et produire l'ordre topologique.

```
__init__(db_conn)   # connexion asyncpg

async resolve(tables: List[TableRef]) -> DependencyGraph
  - Requête sur information_schema :
      SELECT
        tc.table_schema || '.' || tc.table_name  AS dependent_table,
        ccu.table_schema || '.' || ccu.table_name AS depends_on
      FROM information_schema.table_constraints tc
      JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
        AND tc.constraint_schema = rc.constraint_schema
      JOIN information_schema.constraint_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
        AND rc.unique_constraint_schema = ccu.constraint_schema
      WHERE tc.constraint_type = 'FOREIGN KEY'
        AND (tc.table_schema || '.' || tc.table_name) = ANY(<liste_full_names>)
  - Filtre uniquement sur les tables passées en paramètre
  - Applique l'algorithme de Kahn pour le tri topologique
  - Si cycle détecté → lance DependencyResolveError avec les tables impliquées
  - Retourne DependencyGraph

serialize(graph: DependencyGraph) -> dict
  Retourne :
  {
    "version": "1.0",
    "tables": [
      {"schema": "public", "table": "stacks"},
      ...
    ],
    "edges": [
      {"from": "public.services", "to": "public.stacks"},
      ...
    ],
    "ordered": ["public.stacks", "public.services", ...]
  }

deserialize(data: dict) -> DependencyGraph
  - Valide la présence des champs : version, tables, edges, ordered
  - Reconstruit le DependencyGraph
  - Lance DependencyResolveError si structure invalide ou champs manquants
```

---

## 8. `ExportService` (`export_service.py`)

```
__init__(db_conn, git_service: GitService)

async export(tables: List[TableRef]) -> SyncResult
```

### Flux détaillé

```
1. clone_repo()
     → repo_root = await git_service.clone()
     → module_path = git_service.get_module_path(repo_root)

2. resolve_dependencies(tables)
     → graph = await DependencyResolver(db_conn).resolve(tables)

3. write_dependencies(module_path, graph)
     → Sérialise graph via DependencyResolver.serialize()
     → Écrit module_path / "dependencies.json"

4. Pour chaque table dans tables (ordre libre pour l'export) :
     export_table(table, module_path)

5. commit_and_push(repo_root)
     → message : "export(<module_name>): <timestamp ISO 8601> — <n> tables"
     → sha = await git_service.commit_and_push(repo_root, message)

6. Retourne SyncResult

finally:
     git_service.cleanup(repo_root)
```

### `_export_table(table, module_path)`

```
1. Récupère la liste des colonnes depuis information_schema.columns
   pour <schema>.<table>, triées par ordinal_position

2. Exclut :
   - Colonnes présentes dans config.excluded_columns.get(table.full_name, [])
   - Colonnes où is_generated = 'ALWAYS'
   - Colonnes où identity_generation = 'ALWAYS'

3. Construit la requête :
   COPY (SELECT <colonnes_filtrées> FROM <schema>.<table>) TO STDOUT
   WITH (FORMAT CSV, HEADER TRUE)

4. Écrit le résultat en streaming asyncpg dans :
   module_path / "<schema>.<table>.csv"
   (pas de chargement en mémoire)
```

---

## 9. `ImportService` (`import_service.py`)

```
__init__(db_conn, git_service: GitService)

async preview(selected_tables: Optional[List[TableRef]] = None) -> ImportPreview

async import_(selected_tables: Optional[List[TableRef]] = None) -> ImportResult
```

### Flux `preview`

Identique à `import_` pour les phases 1→3, puis :

```
BEGIN
  Pour chaque table (ordre topologique) :
    COUNT lignes à insérer  : NOT MATCHED dans MERGE
    COUNT lignes à modifier : MATCHED avec différence de valeur
    COUNT lignes à supprimer : DELETE orphelins
ROLLBACK   ← rien n'est appliqué
Retourne ImportPreview
```

### Flux `import_`

```
1. clone_repo()
     → repo_root = await git_service.clone()
     → module_path = git_service.get_module_path(repo_root)

2. discover_tables(module_path, selected_tables)
     → Liste les *.csv dans module_path
     → Parse "<schema>.<table>.csv" → TableRef
     → Si selected_tables fourni → filtre
     → Lance TableNotFoundError si un fichier attendu est absent

3. load_dependencies(module_path)
     → Lit dependencies.json
     → DependencyResolver.deserialize()
     → Retourne DependencyGraph avec l'ordre pour les tables découvertes

--- HORS TRANSACTION ---

4. Phase 1 — Création tables temporaires (ordre topologique)
     Pour chaque table :
       CREATE TABLE tmp_<schema>_<table>
         (LIKE <schema>.<table>
          INCLUDING DEFAULTS
          INCLUDING GENERATED
          EXCLUDING CONSTRAINTS
          EXCLUDING INDEXES)

5. Phase 2 — Chargement masse (ordre indépendant, pas de FK dans les tmp)
     Pour chaque table :
       COPY tmp_<schema>_<table> FROM STDIN
       WITH (FORMAT CSV, HEADER TRUE)
       (streaming asyncpg, pas de chargement en mémoire)

6. Phase 3 — Ajout PK sur tables temporaires
     Pour chaque table :
       Récupère colonnes PK depuis information_schema.table_constraints
       + information_schema.key_column_usage
       ALTER TABLE tmp_<schema>_<table> ADD PRIMARY KEY (<pk_columns>)

--- TRANSACTION UNIQUE ---

BEGIN

7. Phase 4 — MERGE INSERT/UPDATE (ordre topologique)
     Pour chaque table :
       Récupère toutes les colonnes depuis information_schema.columns
       Exclut colonnes GENERATED ALWAYS, identity GENERATED ALWAYS,
               colonnes dans excluded_columns
       Construit dynamiquement :

         MERGE INTO <schema>.<table> AS t
         USING tmp_<schema>_<table> AS s
         ON (<pk_join_condition>)
         WHEN MATCHED AND (
           <comparaison colonne par colonne, hors PK et hors colonnes exclues>
         ) THEN
           UPDATE SET <col = s.col, ...>
         WHEN NOT MATCHED THEN
           INSERT (<cols>) VALUES (<s.cols>)

       Comptabilise inserted et updated via RETURNING ou rowcount

8. Phase 5 — Suppressions (ordre topologique INVERSÉ)
     Pour chaque table :
       DELETE FROM <schema>.<table> t
       WHERE NOT EXISTS (
         SELECT 1 FROM tmp_<schema>_<table> s
         WHERE <pk_join_condition>
       )
       Comptabilise deleted

COMMIT

--- TOUJOURS dans un finally ---

9. Phase 6 — Nettoyage tables temporaires (ordre topologique inversé)
     Pour chaque table :
       DROP TABLE IF EXISTS tmp_<schema>_<table>

10. git_service.cleanup(repo_root)

11. Retourne ImportResult
```

### Gestion des erreurs de transaction

Si une exception est levée en phase 4 ou 5 :
- ROLLBACK automatique (asyncpg)
- La base reste intacte
- Les tables `tmp_*` sont supprimées dans le `finally` (hors transaction)
- L'exception est remontée encapsulée dans `ImportConflictError`

---

## 10. Structure du repo Git

```
<repo>/
  docker/
    datas/
      public.stacks.csv
      public.services.csv
      public.networks.csv
      dependencies.json
  workflow/
    datas/
      public.workflow_definitions.csv
      dependencies.json
  roles/
    datas/
      public.roles.csv
      dependencies.json
```

Chaque module est autonome dans son sous-répertoire. Un seul repo, une seule config Git partagée entre modules (repo_url, auth). Le `module_name` est la seule variation.

---

## 11. Contrat d'intégration pour les modules consommateurs

```python
from sdk.git_sync import ExportService, ImportService, GitService
from sdk.git_sync.models import GitConfig, TableRef, AuthMode
from sdk.vault import HarpocrateClient

# Instanciation (une fois au démarrage du module)
vault = HarpocrateClient(...)

git_config = GitConfig(
    repo_url="git@github.com:org/repo.git",
    auth_mode=AuthMode.SSH_KEY,
    auth_secret_ref="${vault://git/docker/ssh_key}",   # référence Harpocrate
    branch="main",
    module_name="docker",
    commit_author_name="ag.flow bot",
    commit_author_email="bot@yoops.org",
    excluded_columns={
        "public.stacks":   ["created_at", "updated_at"],
        "public.services": ["created_at", "updated_at"],
    }
)

git_service = GitService(git_config, vault)

# Tables sélectionnées par l'utilisateur dans l'UI
selected_tables = [
    TableRef(schema="public", table="stacks"),
    TableRef(schema="public", table="services"),
    TableRef(schema="public", table="networks"),
]

# Export
result: SyncResult = await ExportService(db_conn, git_service).export(selected_tables)

# Preview avant import
preview: ImportPreview = await ImportService(db_conn, git_service).preview(selected_tables)
# → afficher preview.tables à l'utilisateur pour confirmation

# Import
result: ImportResult = await ImportService(db_conn, git_service).import_(selected_tables)

# Import depuis un commit historique
git_config_historical = GitConfig(..., target_commit="a3f9c12")
git_service_historical = GitService(git_config_historical, vault)
result = await ImportService(db_conn, git_service_historical).import_(selected_tables)
```

---

## 12. Configuration stockée en base (côté module consommateur)

```json
{
  "repo_url": "git@github.com:org/repo.git",
  "auth_mode": "ssh_key",
  "auth_secret_ref": "${vault://git/docker/ssh_key}",
  "branch": "main",
  "commit_author_name": "ag.flow bot",
  "commit_author_email": "bot@yoops.org",
  "excluded_columns": {
    "public.stacks": ["created_at", "updated_at"],
    "public.services": ["created_at", "updated_at"]
  }
}
```

Le champ s'appelle `auth_secret_ref` (pas `auth_secret`) pour signaler explicitement que c'est une référence à résoudre, jamais une valeur directe en production.

---

## 13. Dépendances techniques

| Dépendance | Usage |
|------------|-------|
| `asyncpg` | Connexions PostgreSQL, COPY streaming |
| `gitpython` ou subprocess | Opérations Git (subprocess recommandé pour le contrôle de l'env) |
| `sdk/vault` | Résolution des secrets Harpocrate |
| `tempfile` (stdlib) | Répertoires et fichiers temporaires |
| `shutil` (stdlib) | Nettoyage répertoires temporaires |

PostgreSQL 17 requis (MERGE natif disponible depuis PG 15, PG 17 en production).

---

## 14. Points d'attention pour le développeur

**Sécurité**
- Aucun credential ne transite dans les logs — les URLs avec token et les clés SSH sont uniquement dans les variables d'env subprocess
- Le fichier clé SSH temporaire est créé avec `chmod 600` et supprimé dans le `finally`
- `auth_secret_ref` en base ne contient jamais la valeur en clair

**Robustesse**
- Le répertoire temporaire Git est toujours supprimé dans un `finally` — pas de fuite possible
- Les tables `tmp_*` sont toujours droppées dans un `finally` — pas de pollution de la base
- La transaction PostgreSQL (phases 4+5) est atomique — pas d'état partiel possible

**Performance**
- L'export et l'import utilisent le COPY streaming asyncpg — aucun CSV chargé en mémoire
- Le MERGE est construit dynamiquement depuis `information_schema` à chaque appel — aucune colonne hardcodée

**Généricité**
- Aucune table métier n'est référencée dans le SDK — tout passe par `TableRef`
- La construction du MERGE est 100% dynamique (colonnes, PK, conditions)
- Le nommage des tables temporaires remplace le `.` du schéma par `_` : `tmp_public_stacks`

**Async**
- Toute la chaîne est async (asyncpg + résolution vault)
- `GitAuthProviderFactory.build()` est async (appel réseau Harpocrate)
- `GitService.__init__()` est sync — la résolution auth est lazy (au premier `clone()`)

---

## 15. Notes d'implémentation (post-livraison)

Lors de la première implémentation (commits `b3b9a24` → `e4707b8`), deux écarts assumés vs cette spec :

1. **MERGE remplacé par INSERT + UPDATE séparés** (phase 4 import). Sémantique identique dans une transaction unique, mais permet d'obtenir des rowcounts précis sur PG 15/16/17. Le `MERGE` de PG 15/16 ne distingue pas INSERT vs UPDATE dans son command tag, et `RETURNING merge_action()` est PG 17 only. Sera reverti au `MERGE` natif si/quand la cible passe en PG 17.

2. **Wrapper `VaultResolver` interne au SDK** plutôt que dépendance directe à un `HarpocrateClient` async. Le SDK Harpocrate actuel (`backend/secrets/`) est sync — `VaultResolver` parse `${vault://...}` et délègue à `SecretsClient.get()` via `asyncio.to_thread`. Le SDK reste autonome (pas de modif Harpocrate).
