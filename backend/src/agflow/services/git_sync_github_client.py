"""Client minimal pour l'API GitHub : parse + list_commits."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
import structlog

_log = structlog.get_logger(__name__)

_SSH_RE = re.compile(r"^git@([^:]+):([^/]+)/(.+?)(?:\.git)?$")
_TIMEOUT = httpx.Timeout(10.0)


class UnsupportedHostError(Exception):
    """Host autre que github.com — listing commits non supporté."""


@dataclass(frozen=True)
class ParsedRepo:
    host: str
    owner: str
    repo: str


@dataclass(frozen=True)
class GitCommit:
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str


def parse_repo_url(repo_url: str) -> ParsedRepo:
    """Parse 'git@github.com:owner/repo.git' OU 'https://github.com/owner/repo(.git)'."""
    m = _SSH_RE.match(repo_url)
    if m is not None:
        host, owner, repo = m.group(1), m.group(2), m.group(3)
        if repo.endswith(".git"):
            repo = repo[:-4]
        return ParsedRepo(host=host, owner=owner, repo=repo)

    parsed = urlparse(repo_url)
    if not parsed.netloc or not parsed.path:
        raise ValueError(f"unparseable repo_url: {repo_url!r}")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"unparseable repo_url: {repo_url!r}")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return ParsedRepo(host=parsed.netloc, owner=owner, repo=repo)


def list_commits_unsupported_check(repo_url: str) -> None:
    """Lève UnsupportedHostError si l'URL ne pointe pas vers github.com."""
    parsed = parse_repo_url(repo_url)
    if parsed.host != "github.com":
        raise UnsupportedHostError(
            f"GitHub API listing not supported for host {parsed.host!r}"
        )


async def list_commits(
    *,
    repo_url: str,
    branch: str,
    limit: int = 30,
    auth_token: str | None = None,
) -> list[GitCommit]:
    """Liste les commits d'une branche via l'API GitHub.

    Lève UnsupportedHostError si host != github.com.
    Lève httpx.HTTPStatusError pour les 4xx/5xx.
    """
    list_commits_unsupported_check(repo_url)
    parsed = parse_repo_url(repo_url)
    url = f"https://api.github.com/repos/{parsed.owner}/{parsed.repo}/commits"
    params = {"sha": branch, "per_page": str(limit)}
    headers = {"Accept": "application/vnd.github+json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    _log.info(
        "git_sync.github.list_commits",
        owner=parsed.owner, repo=parsed.repo, branch=branch, limit=limit,
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()

    out: list[GitCommit] = []
    for item in resp.json():
        sha = item["sha"]
        commit = item["commit"]
        author = commit.get("author") or {}
        out.append(
            GitCommit(
                sha=sha,
                short_sha=sha[:7],
                message=commit.get("message", ""),
                author_name=author.get("name", ""),
                author_email=author.get("email", ""),
                authored_at=datetime.fromisoformat(
                    author.get("date", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
                ),
                html_url=item.get("html_url", ""),
            )
        )
    return out
