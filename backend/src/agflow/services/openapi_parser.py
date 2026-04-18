from __future__ import annotations

import json
import re
from typing import Any

import yaml


def _load_spec(content: str) -> dict[str, Any]:
    """Parse JSON ou YAML automatiquement."""
    content = content.strip()
    if content.startswith("{"):
        return json.loads(content)
    return yaml.safe_load(content)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")


def parse_openapi_tags(spec_content: str) -> list[dict[str, Any]]:
    """Parse un contrat OpenAPI et retourne la liste des tags avec leurs opérations."""
    spec = _load_spec(spec_content)

    declared_tags = {
        t["name"]: t.get("description", "")
        for t in spec.get("tags", [])
    }

    tag_ops: dict[str, list[dict[str, Any]]] = {}
    for path, methods in spec.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(operation, dict):
                continue
            op_tags = operation.get("tags", ["untagged"])
            for tag in op_tags:
                tag_ops.setdefault(tag, []).append({
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "parameters": operation.get("parameters", []),
                    "request_body": operation.get("requestBody"),
                    "responses": operation.get("responses", {}),
                })

    return [
        {
            "slug": _slugify(tag_name),
            "name": tag_name,
            "description": declared_tags.get(tag_name, ""),
            "operation_count": len(ops),
            "operations": ops,
        }
        for tag_name, ops in sorted(tag_ops.items())
    ]


def detect_base_url(spec_content: str) -> str:
    """Extrait base_url depuis servers[0].url si disponible."""
    try:
        spec = _load_spec(spec_content)
        servers = spec.get("servers", [])
        if servers and isinstance(servers[0], dict):
            return servers[0].get("url", "")
    except Exception:
        pass
    return ""


def _extract_body_schema(request_body: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extrait le schema JSON du body (simplifié)."""
    if not request_body:
        return None
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    if not schema:
        return None
    properties = schema.get("properties", {})
    if not properties:
        return schema
    example: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "string")
        if prop_type == "string":
            example[prop_name] = prop_schema.get("example", f"<{prop_name}>")
        elif prop_type == "integer":
            example[prop_name] = prop_schema.get("example", 0)
        elif prop_type == "boolean":
            example[prop_name] = prop_schema.get("example", False)
        elif prop_type == "array":
            example[prop_name] = []
        elif prop_type == "object":
            example[prop_name] = {}
        else:
            example[prop_name] = f"<{prop_name}>"
    return example


def _build_curl(
    op: dict[str, Any],
    base_url: str,
    auth_header: str,
    auth_prefix: str,
    auth_secret_ref: str,
) -> str:
    method = op["method"]
    path = op["path"]
    parts = ["curl -s"]
    if method != "GET":
        parts.append(f"-X {method}")
    if auth_secret_ref:
        parts.append(f'-H "{auth_header}: {auth_prefix} {auth_secret_ref}"')
    if op.get("request_body"):
        parts.append('-H "Content-Type: application/json"')
        body = _extract_body_schema(op["request_body"])
        if body:
            parts.append(f"-d '{json.dumps(body, ensure_ascii=False)}'")
    parts.append(f"{base_url}{path}")
    return " \\\n  ".join(parts)


def generate_tag_markdown(
    tag: dict[str, Any],
    base_url: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str = "",
) -> str:
    """Génère le markdown documentant un tag avec les commandes curl."""
    lines = [f"# {tag['name']}", ""]

    if tag["description"]:
        lines.append(tag["description"])
        lines.append("")

    lines.append(f"Base URL : `{base_url}`")
    if auth_secret_ref:
        lines.append(f"Auth : `{auth_header}: {auth_prefix} {auth_secret_ref}`")
    lines.append("")

    for op in tag.get("operations", []):
        lines.append(f"## {op['method']} {op['path']}")
        if op["summary"]:
            lines.append(op["summary"])
        lines.append("")

        path_params = [p for p in op.get("parameters", []) if p.get("in") == "path"]
        query_params = [p for p in op.get("parameters", []) if p.get("in") == "query"]

        if path_params:
            lines.append("Paramètres URL :")
            for p in path_params:
                req = " (requis)" if p.get("required") else ""
                lines.append(f"- `{p['name']}`{req} — {p.get('description', '')}")
            lines.append("")

        if query_params:
            lines.append("Paramètres query :")
            for p in query_params:
                req = " (requis)" if p.get("required") else ""
                lines.append(f"- `{p['name']}`{req} — {p.get('description', '')}")
            lines.append("")

        if op.get("request_body"):
            body = _extract_body_schema(op["request_body"])
            if body:
                lines.append("Body JSON :")
                lines.append("```json")
                lines.append(json.dumps(body, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("")

        lines.append("```bash")
        lines.append(_build_curl(op, base_url, auth_header, auth_prefix, auth_secret_ref))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def operation_to_filename(operation: dict[str, Any]) -> str:
    """Derive a clean PascalCase .sh filename from the operation."""
    op_id = operation.get("operation_id", "") or operation.get("operationId", "")
    summary = operation.get("summary", "")

    if op_id:
        parts = op_id.split("_")
        api_idx = next((i for i, p in enumerate(parts) if p == "api"), len(parts))
        meaningful = parts[:api_idx]
        if meaningful:
            name = "".join(p.capitalize() for p in meaningful)
        else:
            name = "".join(p.capitalize() for p in parts[:3])
    elif summary:
        name = "".join(w.capitalize() for w in summary.split() if w.isalpha())
    else:
        method = operation.get("method", "Get").capitalize()
        path_parts = [
            p for p in operation.get("path", "").split("/") if p and not p.startswith("{")
        ]
        name = method + "".join(p.capitalize() for p in path_parts[-2:])

    return f"{name}.sh"


def resolve_tag_description(tag: dict[str, Any], overrides: dict[str, str]) -> str:
    """Resolve tag description: manual override > spec description > tag name."""
    override = overrides.get(tag.get("slug", "")) or overrides.get(tag.get("name", ""))
    if override:
        return override
    if tag.get("description"):
        return tag["description"]
    return tag.get("name", "")


def _wrap_comment(text: str, width: int = 74) -> list[str]:
    """Wrap text into lines of max width for bash comments."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len, breaking at word boundary."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def generate_operation_script(
    op: dict[str, Any],
    base_url: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str = "",
) -> str:
    """Generate an executable bash script for a single OpenAPI operation."""
    method = op["method"]
    path = op["path"]
    summary = op.get("summary", "")
    description = op.get("description", "")
    op_name = operation_to_filename(op).replace(".sh", "")

    path_params = [p for p in op.get("parameters", []) if p.get("in") == "path"]
    query_params = [
        p for p in op.get("parameters", []) if p.get("in") == "query" and p.get("required")
    ]

    lines = ["#!/usr/bin/env bash"]

    # Header comment
    lines.append(f"# {op_name} — {summary}")
    if description:
        for desc_line in _wrap_comment(description, 74):
            lines.append(f"# {desc_line}")
    lines.append("#")

    # Usage
    args = [f"<{p['name']}>" for p in path_params]
    args += [f"<{p['name']}>" for p in query_params]
    has_body = method in ("POST", "PUT", "PATCH") and op.get("request_body")
    if has_body:
        args.append("<body_json>")
    if args:
        lines.append(f"# Usage: ./{op_name}.sh {' '.join(args)}")
    lines.append(f"# {method} {path}")
    lines.append("")

    # Arg validation
    arg_idx = 1
    bash_path = path
    for p in path_params:
        var_name = p["name"]
        usage_str = f"./{op_name}.sh {' '.join(args)}"
        lines.append(f'{var_name}="${{{arg_idx}:?Usage: {usage_str}}}"')
        bash_path = bash_path.replace(f"{{{var_name}}}", f"${{{var_name}}}")
        arg_idx += 1

    for p in query_params:
        var_name = p["name"]
        usage_str = f"./{op_name}.sh {' '.join(args)}"
        lines.append(f'{var_name}="${{{arg_idx}:?Usage: {usage_str}}}"')
        arg_idx += 1

    if has_body:
        usage_str = f"./{op_name}.sh {' '.join(args)}"
        lines.append(f'body="${{{arg_idx}:?Usage: {usage_str}}}"')

    if path_params or query_params or has_body:
        lines.append("")

    # Build curl
    curl_parts = ["curl -s"]
    if method != "GET":
        curl_parts.append(f"-X {method}")
    if auth_secret_ref:
        curl_parts.append(f'-H "{auth_header}: {auth_prefix} {auth_secret_ref}"')
    if has_body:
        curl_parts.append('-H "Content-Type: application/json"')
        curl_parts.append('-d "${body}"')

    # URL — base_url is used as-is (it may contain ${VAR} patterns)
    url_str = f'"{base_url}{bash_path}'

    query_vars = [(p["name"], p["name"]) for p in query_params]
    if query_vars:
        qs = "&".join(f"{k}=${{{v}}}" for k, v in query_vars)
        url_str += f"?{qs}"
    url_str += '"'
    curl_parts.append(url_str)

    lines.append(" \\\n  ".join(curl_parts))
    lines.append("")

    return "\n".join(lines)


def generate_tag_index_markdown(
    tag_name: str,
    tag_description: str,
    base_url: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str = "",
    operations: list[dict[str, Any]] | None = None,
) -> str:
    """Generate markdown index for a tag, listing operations with links to .sh scripts."""
    lines = [f"# {tag_name}", ""]
    lines.append(tag_description)
    lines.append("")
    lines.append(f"Base URL : `{base_url}`")
    if auth_secret_ref:
        lines.append(f"Auth : `{auth_header}: {auth_prefix} {auth_secret_ref}`")
    lines.append("")

    for op in operations or []:
        lines.append(f"## {op['name']}")
        if op.get("description"):
            lines.append(op["description"])
        lines.append(f"`{op['path']}`")
        lines.append("")

    return "\n".join(lines)
