from __future__ import annotations

import re

from agflow.services.system_export import export_filename


def test_export_filename_format() -> None:
    name = export_filename()
    assert re.fullmatch(r"agflow-data-\d{8}-\d{6}\.zip", name), name
