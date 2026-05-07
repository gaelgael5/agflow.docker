"""
ag.flow — Storage SDK
Importé comme bibliothèque interne par tous les services qui ont besoin
de lire/écrire des fichiers dans storage_nodes / storage_text / storage_bin.

Dépendances : asyncpg
Usage :
    from storage_sdk import StorageSDK
    storage = StorageSDK(db)  # db = asyncpg connection ou pool
"""

from __future__ import annotations

import asyncpg
from pathlib import Path
from uuid import UUID


# ─── MIME MAP ────────────────────────────────────────────────
# (extension → (mime_type, kind))
# kind : 1 = text | 2 = binary

MIME_MAP: dict[str, tuple[str, int]] = {
    ".md":    ("text/markdown",        1),
    ".txt":   ("text/plain",           1),
    ".toml":  ("text/toml",            1),
    ".json":  ("application/json",     1),
    ".sh":    ("text/x-sh",            1),
    ".py":    ("text/x-python",        1),
    ".j2":    ("text/jinja2",          1),
    ".jinja": ("text/jinja2",          1),
    ".yaml":  ("text/yaml",            1),
    ".yml":   ("text/yaml",            1),
    ".xml":   ("text/xml",             1),
    ".html":  ("text/html",            1),
    ".css":   ("text/css",             1),
    ".js":    ("text/javascript",      1),
    ".ts":    ("text/typescript",      1),
    ".dockerfile": ("text/plain",      1),
    ".png":   ("image/png",            2),
    ".jpg":   ("image/jpeg",           2),
    ".jpeg":  ("image/jpeg",           2),
    ".webp":  ("image/webp",           2),
    ".gif":   ("image/gif",            2),
    ".pdf":   ("application/pdf",      2),
    ".zip":   ("application/zip",      2),
}

_DEFAULT_MIME = ("application/octet-stream", 2)


def _resolve_kind_and_mime(name: str) -> tuple[int, str]:
    """
    Détermine kind (1=text, 2=binary) et mime_type depuis l'extension du nom.
    Les noms sans extension (ex: 'Dockerfile') tombent dans binary par défaut.
    """
    ext = Path(name).suffix.lower()
    # Cas spécial : 'Dockerfile' sans extension → texte
    if not ext and name.lower() in ("dockerfile", "makefile", ".env"):
        return 1, "text/plain"
    mime, kind = MIME_MAP.get(ext, _DEFAULT_MIME)
    return kind, mime


# ─── SDK ─────────────────────────────────────────────────────

class StorageSDK:
    """
    SDK de gestion des fichiers ag.flow.
    Toutes les méthodes sont async et attendent une connexion asyncpg.
    """

    def __init__(self, db: asyncpg.Connection | asyncpg.Pool) -> None:
        self._db = db

    # ── RESOLVE ──────────────────────────────────────────────

    async def resolve_node(
        self,
        name: str,
        parent_id: UUID | None = None,
    ) -> UUID | None:
        """
        Retourne l'UUID d'un node par (parent_id, name).
        Utilise l'index UNIQUE — O(1).
        Retourne None si introuvable.
        """
        if parent_id is not None:
            row = await self._db.fetchrow(
                "SELECT id FROM storage_nodes WHERE parent_id = $1 AND name = $2",
                parent_id, name,
            )
        else:
            row = await self._db.fetchrow(
                "SELECT id FROM storage_nodes WHERE parent_id IS NULL AND name = $1",
                name,
            )
        return row["id"] if row else None

    # ── DELETE ───────────────────────────────────────────────

    async def delete_node(self, id: UUID) -> None:
        """
        Supprime un node et tout son contenu.
        ON DELETE CASCADE dans storage_text/storage_bin gère le nettoyage.
        Pour un folder, la suppression est récursive via CASCADE sur parent_id.
        """
        await self._db.execute(
            "DELETE FROM storage_nodes WHERE id = $1", id
        )

    # ── FOLDERS ──────────────────────────────────────────────

    async def create_folder(
        self,
        name: str,
        parent_id: UUID | None = None,
    ) -> UUID:
        """
        Crée un folder. Idempotent : retourne l'id existant si déjà présent.
        """
        existing = await self.resolve_node(name, parent_id)
        if existing:
            return existing

        return await self._db.fetchval(
            """
            INSERT INTO storage_nodes (parent_id, name, kind)
            VALUES ($1, $2, 0)
            RETURNING id
            """,
            parent_id, name,
        )

    async def create_folder_path(self, path: str) -> UUID:
        """
        Crée récursivement tous les segments d'un chemin slash-séparé.

        Exemple :
            await storage.create_folder_path('/dockerfiles/mistral')
            → crée 'dockerfiles' à la racine, puis 'mistral' dedans.

        Retourne l'UUID du dernier segment (folder le plus profond).
        Idempotent : les segments déjà existants sont réutilisés.
        """
        segments = [s for s in path.strip("/").split("/") if s]
        parent_id: UUID | None = None
        for segment in segments:
            parent_id = await self.create_folder(segment, parent_id)
        return parent_id  # type: ignore[return-value]

    # ── WRITE ────────────────────────────────────────────────

    async def write_document(
        self,
        parent_id: UUID,
        name: str,
        content: str | bytes,
    ) -> UUID:
        """
        Crée ou remplace un document dans un folder.

        Algo :
        1. Résout kind et mime_type depuis l'extension
        2. Résout l'UUID du node si déjà existant
        3. Si inexistant → INSERT storage_nodes + INSERT storage_text/bin
           Si existant   → UPDATE storage_nodes (size, updated_at)
                           DELETE + INSERT storage_text/bin (plus simple qu'UPSERT sur BYTEA)
        4. Retourne l'UUID du node

        Le contenu text est encodé UTF-8 pour le calcul de size.
        """
        kind, mime_type = _resolve_kind_and_mime(name)
        size = (
            len(content.encode("utf-8"))
            if isinstance(content, str)
            else len(content)
        )

        existing_id = await self.resolve_node(name, parent_id)

        if existing_id is None:
            node_id: UUID = await self._db.fetchval(
                """
                INSERT INTO storage_nodes (parent_id, name, kind, mime_type, size)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                parent_id, name, kind, mime_type, size,
            )
        else:
            node_id = existing_id
            await self._db.execute(
                """
                UPDATE storage_nodes
                SET size = $1, updated_at = now()
                WHERE id = $2
                """,
                size, node_id,
            )

        if kind == 1:
            await self._db.execute(
                "DELETE FROM storage_text WHERE node_id = $1", node_id
            )
            await self._db.execute(
                "INSERT INTO storage_text (node_id, content) VALUES ($1, $2)",
                node_id, content,
            )
        else:
            await self._db.execute(
                "DELETE FROM storage_bin WHERE node_id = $1", node_id
            )
            await self._db.execute(
                "INSERT INTO storage_bin (node_id, content) VALUES ($1, $2)",
                node_id, content,
            )

        return node_id

    # ── READ ─────────────────────────────────────────────────

    async def read_node(self, id: UUID) -> dict | None:
        """
        Retourne les métadonnées d'un node + son contenu.
        - kind=0 (folder) → pas de jointure, content=None
        - kind=1 (text)   → jointure storage_text
        - kind=2 (binary) → jointure storage_bin
        Retourne None si le node n'existe pas.
        """
        node = await self._db.fetchrow(
            "SELECT * FROM storage_nodes WHERE id = $1", id
        )
        if not node:
            return None

        result = dict(node)
        result["content"] = None

        if node["kind"] == 1:
            row = await self._db.fetchrow(
                "SELECT content FROM storage_text WHERE node_id = $1", id
            )
            result["content"] = row["content"] if row else None

        elif node["kind"] == 2:
            row = await self._db.fetchrow(
                "SELECT content FROM storage_bin WHERE node_id = $1", id
            )
            result["content"] = row["content"] if row else None

        return result

    async def read_document(self, parent_id: UUID, name: str) -> dict | None:
        """
        Résout un document par (parent_id, name) puis délègue à read_node.
        Retourne None si introuvable.
        """
        node_id = await self.resolve_node(name, parent_id)
        if not node_id:
            return None
        return await self.read_node(node_id)

    async def list_folder(self, folder_id: UUID) -> list[dict]:
        """
        Liste les enfants directs d'un folder (métadonnées uniquement, sans contenu).
        Utile pour afficher une arborescence sans charger les fichiers.
        """
        rows = await self._db.fetch(
            """
            SELECT id, parent_id, name, kind, mime_type, size, created_at, updated_at
            FROM storage_nodes
            WHERE parent_id = $1
            ORDER BY kind ASC, name ASC
            """,
            folder_id,
        )
        return [dict(r) for r in rows]

    # ── MATERIALIZE ──────────────────────────────────────────

    async def write_node_on_disk(self, id: UUID, target_path: Path) -> None:
        """
        Matérialise récursivement un node sur le disque.

        - kind=0 (folder) → crée le répertoire et descend dans les enfants
        - kind=1 (text)   → écrit le fichier texte (UTF-8)
        - kind=2 (binary) → écrit le fichier binaire

        Usage typique avant un run Docker :
            job_dir = Path(f'/tmp/agflow-runs/{job_id}')
            await storage.write_node_on_disk(dockerfile_folder_id, job_dir)
            # Nettoyer après le run : shutil.rmtree(job_dir)
        """
        node = await self.read_node(id)
        if not node:
            return

        if node["kind"] == 0:
            target_path.mkdir(parents=True, exist_ok=True)
            children = await self._db.fetch(
                "SELECT id FROM storage_nodes WHERE parent_id = $1", id
            )
            child_path = target_path / node["name"]
            for child in children:
                await self.write_node_on_disk(child["id"], child_path)

        elif node["kind"] == 1:
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / node["name"]).write_text(
                node["content"] or "", encoding="utf-8"
            )

        elif node["kind"] == 2:
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / node["name"]).write_bytes(node["content"] or b"")
