"""Stream a zip archive of the data volume.

The data volume is the directory pointed at by AGFLOW_DATA_DIR (defaults to
/app/data inside the backend container, bind-mounted from the host as ./data).
We stream the zip without buffering: each file is read and zipped on the fly,
so memory stays flat regardless of the volume size.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path  # noqa: F401  (used in subsequent tasks)


def export_filename() -> str:
    """Return a UTC-timestamped filename like agflow-data-20260429-141500.zip."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"agflow-data-{ts}.zip"
