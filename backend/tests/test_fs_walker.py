from __future__ import annotations

import os

from agflow.services.fs_walker import walk_tree


def test_walk_tree_empty_dirs_listed(tmp_path):
    os.makedirs(tmp_path / "workspace")
    os.makedirs(tmp_path / "output" / "nested")
    (tmp_path / "run.sh").write_bytes(b"#!/bin/sh\n")
    (tmp_path / "output" / "nested" / "log.txt").write_bytes(b"hello")

    entries = walk_tree(str(tmp_path))
    by_path = {e.path: e for e in entries}

    assert by_path["workspace"].type == "dir"
    assert by_path["output"].type == "dir"
    assert by_path["output/nested"].type == "dir"
    assert by_path["run.sh"].type == "file"
    assert by_path["run.sh"].size == 10
    assert by_path["output/nested/log.txt"].type == "file"
    assert by_path["output/nested/log.txt"].size == 5


def test_walk_tree_skips_dot_dirs_except_tmp(tmp_path):
    os.makedirs(tmp_path / ".git")
    os.makedirs(tmp_path / ".tmp")
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / ".tmp" / "run.sh").write_text("#!/bin/sh\n")

    entries = walk_tree(str(tmp_path))
    paths = {e.path for e in entries}

    assert ".tmp" in paths
    assert ".tmp/run.sh" in paths
    assert ".git" not in paths
    assert ".git/config" not in paths


def test_walk_tree_missing_root_returns_empty(tmp_path):
    assert walk_tree(str(tmp_path / "does-not-exist")) == []


def test_walk_tree_root_itself_not_emitted(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    entries = walk_tree(str(tmp_path))
    paths = {e.path for e in entries}
    assert "" not in paths
    assert "." not in paths
