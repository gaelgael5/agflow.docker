from __future__ import annotations

import pytest

from agflow.db.pool import close_pool, get_pool
from agflow.storage import StorageSDK
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


@pytest.fixture
async def storage() -> StorageSDK:
    pool = await get_pool()
    return StorageSDK(pool)


# ── create_folder_path ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_folder_path_creates_nested_folders(storage: StorageSDK) -> None:
    leaf_id = await storage.create_folder_path("/dockerfiles/mistral")

    # Le dernier segment est un folder
    node = await storage.read_node(leaf_id)
    assert node is not None
    assert node["name"] == "mistral"
    assert node["kind"] == 0

    # Le parent "dockerfiles" existe
    parent_id = node["parent_id"]
    parent = await storage.read_node(parent_id)
    assert parent is not None
    assert parent["name"] == "dockerfiles"
    assert parent["parent_id"] is None


@pytest.mark.asyncio
async def test_create_folder_path_is_idempotent(storage: StorageSDK) -> None:
    id1 = await storage.create_folder_path("/a/b/c")
    id2 = await storage.create_folder_path("/a/b/c")
    assert id1 == id2


@pytest.mark.asyncio
async def test_create_folder_path_raises_on_empty(storage: StorageSDK) -> None:
    with pytest.raises(ValueError):
        await storage.create_folder_path("")


@pytest.mark.asyncio
async def test_create_folder_path_raises_on_slash_only(storage: StorageSDK) -> None:
    with pytest.raises(ValueError):
        await storage.create_folder_path("///")


# ── write_document ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_document_creates_text_file(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("docs")

    node_id = await storage.write_document(folder_id, "readme.md", "# Hello")

    node = await storage.read_node(node_id)
    assert node is not None
    assert node["name"] == "readme.md"
    assert node["kind"] == 1
    assert node["mime_type"] == "text/markdown"
    assert node["content"] == "# Hello"
    assert node["size"] == len(b"# Hello")


@pytest.mark.asyncio
async def test_write_document_updates_existing(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("docs")

    id1 = await storage.write_document(folder_id, "config.toml", "version = 1")
    id2 = await storage.write_document(folder_id, "config.toml", "version = 2")

    # Même UUID — pas de doublon
    assert id1 == id2

    node = await storage.read_node(id1)
    assert node is not None
    assert node["content"] == "version = 2"


@pytest.mark.asyncio
async def test_write_document_binary(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("assets")
    data = b"\x89PNG\r\n\x1a\n"  # magic bytes PNG

    node_id = await storage.write_document(folder_id, "logo.png", data)

    node = await storage.read_node(node_id)
    assert node is not None
    assert node["kind"] == 2
    assert node["mime_type"] == "image/png"
    assert node["content"] == data


@pytest.mark.asyncio
async def test_write_document_dockerfile_no_extension(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("build")

    node_id = await storage.write_document(folder_id, "Dockerfile", "FROM python:3.12")

    node = await storage.read_node(node_id)
    assert node is not None
    assert node["kind"] == 1
    assert node["content"] == "FROM python:3.12"


# ── read_document ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_document_returns_none_if_missing(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("empty")
    result = await storage.read_document(folder_id, "ghost.md")
    assert result is None


@pytest.mark.asyncio
async def test_read_document_after_write(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("notes")
    await storage.write_document(folder_id, "note.txt", "bonjour")

    doc = await storage.read_document(folder_id, "note.txt")
    assert doc is not None
    assert doc["content"] == "bonjour"
    assert doc["name"] == "note.txt"


# ── delete_node ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_node_removes_file(storage: StorageSDK) -> None:
    folder_id = await storage.create_folder("trash")
    node_id = await storage.write_document(folder_id, "bye.txt", "see you")

    await storage.delete_node(node_id)

    assert await storage.read_node(node_id) is None


@pytest.mark.asyncio
async def test_delete_node_cascades_to_children(storage: StorageSDK) -> None:
    root_id = await storage.create_folder_path("/root/sub")
    sub_id = await storage.resolve_node("sub", root_id)
    assert sub_id is not None

    file_id = await storage.write_document(sub_id, "child.txt", "child")

    # Supprimer root supprime sub et child
    await storage.delete_node(root_id)

    assert await storage.read_node(root_id) is None
    assert await storage.read_node(sub_id) is None
    assert await storage.read_node(file_id) is None


# ── write_node_on_disk ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_node_on_disk_materializes_folder(
    storage: StorageSDK, tmp_path
) -> None:
    # Arborescence : root_folder/subdir/ + root_folder/readme.md + root_folder/data.bin
    root_id = await storage.create_folder("run")
    sub_id = await storage.create_folder("subdir", root_id)
    await storage.write_document(sub_id, "nested.txt", "deep")
    await storage.write_document(root_id, "readme.md", "# Run")
    await storage.write_document(root_id, "data.bin", b"\x00\x01\x02")

    await storage.write_node_on_disk(root_id, tmp_path)

    run_dir = tmp_path / "run"
    assert (run_dir / "readme.md").read_text(encoding="utf-8") == "# Run"
    assert (run_dir / "data.bin").read_bytes() == b"\x00\x01\x02"
    assert (run_dir / "subdir" / "nested.txt").read_text(encoding="utf-8") == "deep"


@pytest.mark.asyncio
async def test_write_node_on_disk_single_text_file(
    storage: StorageSDK, tmp_path
) -> None:
    folder_id = await storage.create_folder("solo")
    file_id = await storage.write_document(folder_id, "hello.txt", "world")

    await storage.write_node_on_disk(file_id, tmp_path)

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "world"


@pytest.mark.asyncio
async def test_write_node_on_disk_unknown_id_is_noop(
    storage: StorageSDK, tmp_path
) -> None:
    import uuid
    # Ne doit pas lever d'exception
    await storage.write_node_on_disk(uuid.uuid4(), tmp_path)
