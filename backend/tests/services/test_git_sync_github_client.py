"""Tests du github_client : parse_repo_url + list_commits (mock httpx)."""
from __future__ import annotations

import httpx
import pytest

from agflow.services import git_sync_github_client as gh

# ─── parse_repo_url ─────────────────────────────────────────────────────

def test_parse_https_url():
    parsed = gh.parse_repo_url("https://github.com/gaelgael5/agflow-sync")
    assert parsed.host == "github.com"
    assert parsed.owner == "gaelgael5"
    assert parsed.repo == "agflow-sync"


def test_parse_https_url_with_git_suffix():
    parsed = gh.parse_repo_url("https://github.com/gaelgael5/agflow-sync.git")
    assert parsed.repo == "agflow-sync"


def test_parse_ssh_url():
    parsed = gh.parse_repo_url("git@github.com:gaelgael5/agflow-sync.git")
    assert parsed.host == "github.com"
    assert parsed.owner == "gaelgael5"
    assert parsed.repo == "agflow-sync"


def test_parse_unsupported_host():
    with pytest.raises(gh.UnsupportedHostError):
        gh.list_commits_unsupported_check("https://gitlab.com/owner/repo")


# ─── list_commits (mocked httpx) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_commits_returns_parsed_data(monkeypatch):
    payload = [
        {
            "sha": "abc1234567890",
            "commit": {
                "message": "feat: hello",
                "author": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-05-17T10:00:00Z",
                },
            },
            "html_url": "https://github.com/owner/repo/commit/abc1234567890",
        }
    ]

    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    commits = await gh.list_commits(
        repo_url="https://github.com/owner/repo",
        branch="main",
        limit=10,
    )
    assert len(commits) == 1
    assert commits[0].sha == "abc1234567890"
    assert commits[0].short_sha == "abc1234"
    assert commits[0].author_name == "Alice"
    assert commits[0].html_url == "https://github.com/owner/repo/commit/abc1234567890"


@pytest.mark.asyncio
async def test_list_commits_raises_on_404(monkeypatch):
    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(404, json={"message": "Not Found"},
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    with pytest.raises(httpx.HTTPStatusError):
        await gh.list_commits(
            repo_url="https://github.com/owner/repo",
            branch="main",
        )


@pytest.mark.asyncio
async def test_list_commits_raises_unsupported_for_gitlab():
    with pytest.raises(gh.UnsupportedHostError):
        await gh.list_commits(
            repo_url="https://gitlab.com/owner/repo",
            branch="main",
        )
