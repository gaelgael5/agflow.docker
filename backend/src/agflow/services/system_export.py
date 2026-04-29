"""Stream a zip archive of the data volume.

The data volume is the directory pointed at by AGFLOW_DATA_DIR (defaults to
/app/data inside the backend container, bind-mounted from the host as ./data).
We stream the zip without buffering: each file is read and zipped on the fly,
so memory stays flat regardless of the volume size.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path


def export_filename() -> str:
    """Return a UTC-timestamped filename like agflow-data-20260429-141500.zip."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
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
