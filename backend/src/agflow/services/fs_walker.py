"""Filesystem walker shared by services that expose file trees to the UI.

Yields both files AND directories (including empty ones) so that the frontend
explorer can display directory nodes that exist on disk but contain no files
yet (e.g. workspace/ created by container mounts).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FsEntry:
    path: str  # POSIX-style relative path from root, no trailing slash
    type: str  # "file" or "dir"
    full_path: str  # absolute path on disk
    size: int  # bytes for files, 0 for dirs


def walk_tree(
    root: str,
    *,
    keep_dot_dirs: tuple[str, ...] = (".tmp",),
    skip_dot_dirs: bool = True,
) -> list[FsEntry]:
    """Walk root recursively, returning entries for files and directories.

    Empty directories are returned as their own entry — the FileTree on the
    frontend can then render them even before any file is created inside.

    Dot-prefixed directories are skipped unless their name is in
    ``keep_dot_dirs`` (default keeps .tmp, used by container_runner).
    Set ``skip_dot_dirs=False`` to include all dot directories.
    The root itself is never emitted.
    """
    if not os.path.isdir(root):
        return []
    entries: list[FsEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if skip_dot_dirs:
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") or d in keep_dot_dirs
            ]
        # Emit each subdirectory (skip the root itself).
        for dname in dirnames:
            full = os.path.join(dirpath, dname)
            rel = os.path.relpath(full, root).replace("\\", "/")
            entries.append(FsEntry(path=rel, type="dir", full_path=full, size=0))
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            entries.append(FsEntry(path=rel, type="file", full_path=full, size=size))
    entries.sort(key=lambda e: e.path)
    return entries
