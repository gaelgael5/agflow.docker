from __future__ import annotations

import re

from agflow.services.system_export import export_filename


def test_export_filename_format() -> None:
    name = export_filename()
    assert re.fullmatch(r"agflow-data-\d{8}-\d{6}\.zip", name), name


from pathlib import Path

import pytest

from agflow.services.system_export import _iter_files


def test_iter_files_yields_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"world")

    rels = sorted(rel for rel, _ in _iter_files(tmp_path))
    assert rels == ["a.txt", "sub/b.txt"]


def test_iter_files_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    (tmp_path / "f.txt").write_bytes(b"x")
    rels = [rel for rel, _ in _iter_files(tmp_path)]
    assert rels == ["f.txt"]


def test_iter_files_returns_empty_when_root_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list(_iter_files(missing)) == []


def test_iter_files_returns_empty_when_root_is_empty(tmp_path: Path) -> None:
    assert list(_iter_files(tmp_path)) == []
