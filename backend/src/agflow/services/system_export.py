"""Stream a zip archive of the data volume.

The data volume is the directory pointed at by AGFLOW_DATA_DIR (defaults to
/app/data inside the backend container, bind-mounted from the host as ./data).
We stream the zip without buffering: each file is read and zipped on the fly,
so memory stays flat regardless of the volume size.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import structlog
from stream_zip import ZIP_64, async_stream_zip

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_PERMS = 0o644


def export_filename() -> str:
    """Return a UTC-timestamped filename like agflow-data-20260429-141500.zip."""
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"agflow-data-{ts}.zip"


def _iter_files(root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (relative_posix_path, absolute_path) for every regular file under root.

    Empty directories and broken symlinks are skipped. If root does not exist or
    is not a directory, the iterator yields nothing (no exception).
    """
    if not root.exists() or not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        yield rel, p


async def iter_data_zip(root: Path, *, user_id: str) -> AsyncIterator[bytes]:
    """Stream a zip archive of `root` as bytes chunks.

    Yields raw zip bytes suitable for an HTTP StreamingResponse. The archive is
    flat (paths inside the zip are relative to `root`). When `root` is missing
    or empty, yields a valid empty zip. Logs total size & duration on completion.
    """
    started = datetime.now(UTC)
    total = 0

    async def _members():
        modified = datetime.now(UTC)
        for rel, abs_path in _iter_files(root):
            yield rel, modified, _DEFAULT_PERMS, ZIP_64, _read_file_chunks(abs_path)

    async for chunk in async_stream_zip(_members()):
        total += len(chunk)
        yield chunk

    duration = (datetime.now(UTC) - started).total_seconds()
    logger.info(
        "system.export",
        user_id=user_id,
        size_bytes=total,
        duration_s=round(duration, 3),
    )


async def _read_file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as f:
        while True:
            buf = f.read(_CHUNK_SIZE)
            if not buf:
                return
            yield buf
