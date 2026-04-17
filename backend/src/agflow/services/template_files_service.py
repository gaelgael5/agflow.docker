from __future__ import annotations

import json
import os
import shutil

import structlog

_log = structlog.get_logger(__name__)


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _templates_dir() -> str:
    return os.path.join(_data_dir(), "templates")


def _template_dir(slug: str) -> str:
    return os.path.join(_templates_dir(), slug)


def _extract_culture(filename: str) -> str:
    return filename.split(".")[0] if "." in filename else ""


def list_all() -> list[dict]:
    base = _templates_dir()
    if not os.path.isdir(base):
        return []
    results = []
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        if not os.path.isdir(d):
            continue
        meta = read_meta(slug)
        if meta is None:
            continue
        j2_files = [f for f in os.listdir(d) if f.endswith(".j2")]
        cultures = sorted(set(_extract_culture(f) for f in j2_files if _extract_culture(f)))
        results.append({
            "slug": slug,
            "display_name": meta.get("display_name", slug),
            "description": meta.get("description", ""),
            "cultures": cultures,
        })
    return results


def read_meta(slug: str) -> dict | None:
    path = os.path.join(_template_dir(slug), "template.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def write_meta(slug: str, meta: dict) -> None:
    d = _template_dir(slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "template.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))


def create(slug: str, display_name: str, description: str = "") -> dict:
    d = _template_dir(slug)
    if os.path.isdir(d):
        raise FileExistsError(f"Template '{slug}' already exists")
    write_meta(slug, {"display_name": display_name, "description": description})
    _log.info("template_files.create", slug=slug)
    return {"slug": slug, "display_name": display_name, "description": description, "cultures": []}


def update(slug: str, display_name: str | None = None, description: str | None = None) -> dict:
    meta = read_meta(slug)
    if meta is None:
        raise FileNotFoundError(f"Template '{slug}' not found")
    if display_name is not None:
        meta["display_name"] = display_name
    if description is not None:
        meta["description"] = description
    write_meta(slug, meta)
    _log.info("template_files.update", slug=slug)
    summary = list_all()
    return next((t for t in summary if t["slug"] == slug), meta)


def delete(slug: str) -> None:
    d = _template_dir(slug)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"Template '{slug}' not found")
    shutil.rmtree(d)
    _log.info("template_files.delete", slug=slug)


def list_files(slug: str) -> list[dict]:
    d = _template_dir(slug)
    if not os.path.isdir(d):
        return []
    results = []
    for filename in sorted(os.listdir(d)):
        if not filename.endswith(".j2"):
            continue
        full = os.path.join(d, filename)
        results.append({
            "filename": filename,
            "culture": _extract_culture(filename),
            "size": os.path.getsize(full),
        })
    return results


def read_file(slug: str, filename: str) -> str:
    path = os.path.join(_template_dir(slug), filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File '{filename}' not found in template '{slug}'")
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_file(slug: str, filename: str, content: str) -> None:
    d = _template_dir(slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, filename), "w", encoding="utf-8") as f:
        f.write(content)
    _log.info("template_files.write_file", slug=slug, filename=filename)


def delete_file(slug: str, filename: str) -> None:
    path = os.path.join(_template_dir(slug), filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File '{filename}' not found in template '{slug}'")
    os.unlink(path)
    _log.info("template_files.delete_file", slug=slug, filename=filename)


def get_detail(slug: str) -> dict:
    meta = read_meta(slug)
    if meta is None:
        raise FileNotFoundError(f"Template '{slug}' not found")
    return {
        "slug": slug,
        "display_name": meta.get("display_name", slug),
        "description": meta.get("description", ""),
        "files": list_files(slug),
    }
