# ag.flow — Storage SDK — Spécification API

## Vue d'ensemble

Le Storage SDK est une bibliothèque Python interne (`storage_sdk.py`) importée par tous les services ag.flow qui ont besoin de lire ou écrire des fichiers. Il n'y a pas de microservice dédié — le SDK s'instancie avec une connexion asyncpg et s'utilise directement dans le contexte appelant.

```python
from storage_sdk import StorageSDK
storage = StorageSDK(db)  # db = asyncpg.Connection ou asyncpg.Pool
```

## Modèle de données

### Concepts

Le stockage repose sur trois tables :

- `storage_nodes` : tous les nœuds (folders, fichiers texte, fichiers binaires)
- `storage_text` : contenu des fichiers texte (jointure 1-1 sur `storage_nodes`)
- `storage_bin` : contenu des fichiers binaires (jointure 1-1 sur `storage_nodes`)

### Discriminant `kind`

| Valeur | Type | Table de contenu |
|--------|------|-----------------|
| `0` | Folder | aucune |
| `1` | Fichier texte | `storage_text` |
| `2` | Fichier binaire | `storage_bin` |

### Arborescence

L'arborescence est modélisée par `parent_id` auto-référentiel. Un nœud racine a `parent_id = NULL`. Il n'y a pas de profondeur maximum.

La contrainte `UNIQUE (parent_id, name)` garantit qu'un nom est unique dans un folder donné.

### Cascade

`ON DELETE CASCADE` est positionné sur :
- `storage_nodes.parent_id` → supprimer un folder supprime tous ses enfants récursivement
- `storage_text.node_id` → supprimer un node supprime son contenu texte
- `storage_bin.node_id` → supprimer un node supprime son contenu binaire

---

## API

### `resolve_node(name, parent_id?) → UUID | None`

Résout l'UUID d'un nœud par son nom dans un folder.

**Paramètres**
- `name` : nom du nœud
- `parent_id` *(optionnel)* : UUID du folder parent. Si absent, recherche à la racine.

**Retour**
- UUID du nœud si trouvé, `None` sinon.

**Algo**
1. Si `parent_id` fourni → `WHERE parent_id = $1 AND name = $2`
2. Sinon → `WHERE parent_id IS NULL AND name = $1`
3. Utilise l'index UNIQUE — O(1)

---

### `delete_node(id)`

Supprime un nœud et tout son contenu.

**Paramètres**
- `id` : UUID du nœud à supprimer

**Algo**
1. `DELETE FROM storage_nodes WHERE id = $1`
2. Les CASCADE gèrent automatiquement `storage_text`, `storage_bin`, et les enfants (folders)

---

### `create_folder(name, parent_id?) → UUID`

Crée un folder. Idempotent.

**Paramètres**
- `name` : nom du folder
- `parent_id` *(optionnel)* : UUID du folder parent. Si absent, crée à la racine.

**Retour**
- UUID du folder (existant ou nouvellement créé)

**Algo**
1. `resolve_node(name, parent_id)`
2. Si existe → retourne l'UUID existant
3. Sinon → `INSERT INTO storage_nodes (parent_id, name, kind=0)` → retourne le nouvel UUID

---

### `create_folder_path(path) → UUID`

Crée récursivement tous les segments d'un chemin.

**Paramètres**
- `path` : chemin slash-séparé, ex : `/dockerfiles/mistral`

**Retour**
- UUID du dernier segment (folder le plus profond)

**Algo**
1. Split `path` sur `/`, filtre les segments vides
2. Pour chaque segment → `create_folder(segment, parent_id_courant)`
3. L'`parent_id` du tour suivant est l'UUID retourné au tour précédent
4. Retourne l'UUID du dernier segment

**Idempotence** : les segments déjà existants sont réutilisés via `create_folder`.

---

### `write_document(parent_id, name, content) → UUID`

Crée ou remplace un document dans un folder.

**Paramètres**
- `parent_id` : UUID du folder cible
- `name` : nom du fichier avec extension (ex : `Dockerfile`, `config.toml`)
- `content` : `str` pour les fichiers texte, `bytes` pour les binaires

**Retour**
- UUID du nœud (créé ou existant)

**Algo**
1. `_resolve_kind_and_mime(name)` → détermine `kind` (1 ou 2) et `mime_type` depuis l'extension
2. Calcule `size` : `len(content.encode('utf-8'))` si str, `len(content)` si bytes
3. `resolve_node(name, parent_id)` → cherche un nœud existant
4. **Si inexistant** :
   - `INSERT INTO storage_nodes` avec `parent_id, name, kind, mime_type, size`
5. **Si existant** :
   - `UPDATE storage_nodes SET size, updated_at`
6. Selon `kind` :
   - `kind=1` → `DELETE FROM storage_text` + `INSERT INTO storage_text`
   - `kind=2` → `DELETE FROM storage_bin` + `INSERT INTO storage_bin`
7. Retourne l'UUID du nœud

**Note** : le DELETE + INSERT sur le contenu est intentionnel — plus simple et sans ambiguïté qu'un UPSERT sur BYTEA.

---

### `read_node(id) → dict | None`

Retourne les métadonnées d'un nœud et son contenu.

**Paramètres**
- `id` : UUID du nœud

**Retour**
```python
{
  "id": UUID,
  "parent_id": UUID | None,
  "name": str,
  "kind": int,          # 0 | 1 | 2
  "mime_type": str | None,
  "size": int | None,
  "created_at": datetime,
  "updated_at": datetime,
  "content": str | bytes | None   # None si kind=0 (folder)
}
```

**Algo**
1. `SELECT * FROM storage_nodes WHERE id = $1`
2. Si `kind=1` → `SELECT content FROM storage_text WHERE node_id = $1`
3. Si `kind=2` → `SELECT content FROM storage_bin WHERE node_id = $1`
4. Si `kind=0` → `content = None` (pas de jointure)

**Note** : pas de jointure pour les folders — c'est intentionnel pour éviter les jointures inutiles.

---

### `read_document(parent_id, name) → dict | None`

Résout un document par son nom dans un folder puis retourne son contenu.

**Paramètres**
- `parent_id` : UUID du folder
- `name` : nom du fichier

**Retour**
- Même structure que `read_node`, ou `None` si introuvable.

**Algo**
1. `resolve_node(name, parent_id)` → UUID
2. Si None → retourne None
3. Sinon → `read_node(uuid)`

---

### `list_folder(folder_id) → list[dict]`

Liste les enfants directs d'un folder (métadonnées uniquement, sans contenu).

**Paramètres**
- `folder_id` : UUID du folder

**Retour**
- Liste de dicts avec `id, parent_id, name, kind, mime_type, size, created_at, updated_at`
- Triée : folders (kind=0) en premier, puis ordre alphabétique

**Algo**
1. `SELECT ... FROM storage_nodes WHERE parent_id = $1 ORDER BY kind ASC, name ASC`

---

### `write_node_on_disk(id, target_path)`

Matérialise récursivement un nœud sur le disque. Utilisé juste avant un run Docker.

**Paramètres**
- `id` : UUID du nœud racine à matérialiser
- `target_path` : `pathlib.Path` du répertoire cible

**Algo**
1. `read_node(id)`
2. **Si kind=0 (folder)** :
   - `target_path.mkdir(parents=True, exist_ok=True)`
   - `SELECT id FROM storage_nodes WHERE parent_id = $1`
   - Pour chaque enfant → récursion sur `target_path / node["name"]`
3. **Si kind=1 (text)** :
   - `target_path.mkdir(parents=True, exist_ok=True)`
   - `(target_path / name).write_text(content, encoding='utf-8')`
4. **Si kind=2 (binary)** :
   - `target_path.mkdir(parents=True, exist_ok=True)`
   - `(target_path / name).write_bytes(content)`

**Pattern d'usage recommandé** :
```python
job_dir = Path(f"/tmp/agflow-runs/{job_id}")
await storage.write_node_on_disk(folder_id, job_dir)
# ... exécution Docker avec volume monté sur job_dir ...
shutil.rmtree(job_dir)  # nettoyage après le run
```

---

## Résolution MIME

La fonction interne `_resolve_kind_and_mime(name)` détermine automatiquement `kind` et `mime_type` depuis l'extension.

| Extension | mime_type | kind |
|-----------|-----------|------|
| `.md` | text/markdown | 1 |
| `.txt` | text/plain | 1 |
| `.toml` | text/toml | 1 |
| `.json` | application/json | 1 |
| `.sh` | text/x-sh | 1 |
| `.py` | text/x-python | 1 |
| `.j2` / `.jinja` | text/jinja2 | 1 |
| `.yaml` / `.yml` | text/yaml | 1 |
| `.xml` | text/xml | 1 |
| `.html` | text/html | 1 |
| `Dockerfile` *(sans ext)* | text/plain | 1 |
| `.png` | image/png | 2 |
| `.jpg` / `.jpeg` | image/jpeg | 2 |
| `.webp` | image/webp | 2 |
| `.pdf` | application/pdf | 2 |
| *(inconnu)* | application/octet-stream | 2 |

---

## Indexes

| Index | Colonne(s) | Usage |
|-------|-----------|-------|
| UNIQUE constraint | `(parent_id, name)` | resolve_node — O(1) |
| `idx_storage_nodes_parent_id` | `parent_id` | list_folder, write_node_on_disk |
| `idx_storage_nodes_kind` | `kind` | filtrage par type |
| `idx_storage_nodes_updated_at` | `updated_at DESC` | listing récent, audit |

Les tables `storage_text` et `storage_bin` n'ont pas d'index supplémentaires — `node_id` est PRIMARY KEY, toutes les lectures passent par `node_id`.
