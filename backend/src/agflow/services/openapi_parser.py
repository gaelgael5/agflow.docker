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
