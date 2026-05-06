from __future__ import annotations

from pathlib import Path

MIME_MAP: dict[str, tuple[str, int]] = {
    ".md":         ("text/markdown",        1),
    ".txt":        ("text/plain",           1),
    ".toml":       ("text/toml",            1),
    ".json":       ("application/json",     1),
    ".sh":         ("text/x-sh",            1),
    ".py":         ("text/x-python",        1),
    ".j2":         ("text/jinja2",          1),
    ".jinja":      ("text/jinja2",          1),
    ".yaml":       ("text/yaml",            1),
    ".yml":        ("text/yaml",            1),
    ".xml":        ("text/xml",             1),
    ".html":       ("text/html",            1),
    ".css":        ("text/css",             1),
    ".js":         ("text/javascript",      1),
    ".ts":         ("text/typescript",      1),
    ".dockerfile": ("text/plain",           1),
    ".png":        ("image/png",            2),
    ".jpg":        ("image/jpeg",           2),
    ".jpeg":       ("image/jpeg",           2),
    ".webp":       ("image/webp",           2),
    ".gif":        ("image/gif",            2),
    ".pdf":        ("application/pdf",      2),
    ".zip":        ("application/zip",      2),
}

_DEFAULT_MIME = ("application/octet-stream", 2)

_TEXT_NO_EXT = {"dockerfile", "makefile", ".env"}


def resolve_kind_and_mime(name: str) -> tuple[int, str]:
    """Retourne (kind, mime_type) depuis l'extension du nom de fichier.

    kind : 1 = texte, 2 = binaire.
    Les noms sans extension connus (Dockerfile, Makefile, .env) → kind=1.
    Tout inconnu → kind=2 / application/octet-stream.
    """
    ext = Path(name).suffix.lower()
    if not ext and name.lower() in _TEXT_NO_EXT:
        return 1, "text/plain"
    mime, kind = MIME_MAP.get(ext, _DEFAULT_MIME)
    return kind, mime
