from __future__ import annotations

from pathlib import Path
from uuid import UUID

import asyncpg

from .mime import resolve_kind_and_mime


class StorageSDK:
    """SDK de gestion des fichiers ag.flow stockés dans PostgreSQL.

    Toutes les méthodes sont async. Passer une connexion ou un pool asyncpg.
    La gestion des transactions est à la charge de l'appelant.
    """

    def __init__(self, db: asyncpg.Connection | asyncpg.Pool) -> None:
        self._db = db

    # ── RESOLVE ──────────────────────────────────────────────────────────────

    async def resolve_node(
        self,
        name: str,
        parent_id: UUID | None = None,
    ) -> UUID | None:
        """UUID d'un node par (parent_id, name). None si introuvable. O(1)."""
        if parent_id is not None:
            row = await self._db.fetchrow(
                "SELECT id FROM storage_nodes WHERE parent_id = $1 AND name = $2",
                parent_id,
                name,
            )
        else:
            row = await self._db.fetchrow(
                "SELECT id FROM storage_nodes WHERE parent_id IS NULL AND name = $1",
                name,
            )
        return row["id"] if row else None

    # ── DELETE ───────────────────────────────────────────────────────────────

    async def delete_node(self, id: UUID) -> None:
        """Supprime un node. CASCADE supprime le contenu et les enfants."""
        await self._db.execute("DELETE FROM storage_nodes WHERE id = $1", id)

    # ── FOLDERS ──────────────────────────────────────────────────────────────

    async def create_folder(
        self,
        name: str,
        parent_id: UUID | None = None,
    ) -> UUID:
        """Crée un folder. Idempotent : retourne l'UUID existant si déjà présent."""
        existing = await self.resolve_node(name, parent_id)
        if existing:
            return existing

        return await self._db.fetchval(
            """
            INSERT INTO storage_nodes (parent_id, name, kind)
            VALUES ($1, $2, 0)
            RETURNING id
            """,
            parent_id,
            name,
        )

    async def create_folder_path(self, path: str) -> UUID:
        """Crée récursivement tous les segments d'un chemin slash-séparé.

        Exemple : '/dockerfiles/mistral' crée 'dockerfiles' à la racine
        puis 'mistral' dedans. Idempotent. Retourne l'UUID du dernier segment.

        Raises ValueError si le chemin est vide ou ne contient que des slashes.
        """
        segments = [s for s in path.strip("/").split("/") if s]
        if not segments:
            raise ValueError(f"Chemin invalide (vide ou uniquement des slashes) : {path!r}")

        parent_id: UUID | None = None
        for segment in segments:
            parent_id = await self.create_folder(segment, parent_id)
        return parent_id  # type: ignore[return-value]

    # ── WRITE ─────────────────────────────────────────────────────────────────

    async def write_document(
        self,
        parent_id: UUID,
        name: str,
        content: str | bytes,
    ) -> UUID:
        """Crée ou remplace un document dans un folder.

        Détermine kind/mime depuis l'extension. Si le node existe déjà, met à
        jour size et remplace le contenu (DELETE + INSERT plus simple qu'UPSERT
        sur BYTEA).
        """
        kind, mime_type = resolve_kind_and_mime(name)
        size = (
            len(content.encode("utf-8")) if isinstance(content, str) else len(content)
        )

        existing_id = await self.resolve_node(name, parent_id)

        if existing_id is None:
            node_id: UUID = await self._db.fetchval(
                """
                INSERT INTO storage_nodes (parent_id, name, kind, mime_type, size)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                parent_id,
                name,
                kind,
                mime_type,
                size,
            )
        else:
            node_id = existing_id
            await self._db.execute(
                "UPDATE storage_nodes SET size = $1, updated_at = now() WHERE id = $2",
                size,
                node_id,
            )

        if kind == 1:
            await self._db.execute("DELETE FROM storage_text WHERE node_id = $1", node_id)
            await self._db.execute(
                "INSERT INTO storage_text (node_id, content) VALUES ($1, $2)",
                node_id,
                content,
            )
        else:
            await self._db.execute("DELETE FROM storage_bin WHERE node_id = $1", node_id)
            await self._db.execute(
                "INSERT INTO storage_bin (node_id, content) VALUES ($1, $2)",
                node_id,
                content,
            )

        return node_id

    # ── READ ──────────────────────────────────────────────────────────────────

    async def read_node(self, id: UUID) -> dict | None:
        """Métadonnées + contenu d'un node. None si inexistant.

        kind=0 (folder) → content=None (pas de jointure).
        kind=1 (texte)  → jointure storage_text.
        kind=2 (binaire) → jointure storage_bin.
        """
        node = await self._db.fetchrow("SELECT * FROM storage_nodes WHERE id = $1", id)
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
        """Résout un document par (parent_id, name) puis lit le node. None si introuvable."""
        node_id = await self.resolve_node(name, parent_id)
        if not node_id:
            return None
        return await self.read_node(node_id)

    async def list_folder(self, folder_id: UUID) -> list[dict]:
        """Enfants directs d'un folder (métadonnées uniquement, sans contenu).

        Triés : folders (kind=0) en premier, puis ordre alphabétique.
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

    # ── MATERIALIZE ───────────────────────────────────────────────────────────

    async def write_node_on_disk(self, id: UUID, target_path: Path) -> None:
        """Matérialise récursivement un node sur le disque.

        kind=0 (folder) → crée le répertoire et descend dans les enfants.
        kind=1 (texte)  → écrit le fichier texte UTF-8.
        kind=2 (binaire) → écrit le fichier binaire.

        Usage avant un run Docker :
            job_dir = Path(f'/tmp/agflow-runs/{job_id}')
            await storage.write_node_on_disk(folder_id, job_dir)
            # après le run : shutil.rmtree(job_dir)
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
