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


def _resolve_ref(ref: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a JSON $ref like '#/components/schemas/AgentCreate'."""
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node.get(part, {})
    return node


def _example_value(name: str, schema: dict[str, Any]) -> Any:
    """Generate a plausible example value for a schema property."""
    if "example" in schema:
        return schema["example"]
    if schema.get("examples"):
        return schema["examples"][0]
    if "default" in schema:
        return schema["default"]

    prop_type = schema.get("type", "string")
    if "email" in name:
        return "user@example.com"
    if "url" in name or "uri" in name:
        return "https://example.com"
    if "password" in name or "secret" in name or "token" in name:
        return "changeme"
    if "name" in name or "display" in name:
        return f"my-{name.replace('_', '-')}"
    if name in ("slug", "id"):
        return "my-item"
    if "description" in name:
        return ""

    if prop_type == "string":
        if "enum" in schema:
            return schema["enum"][0]
        return f"<{name}>"
    if prop_type == "integer":
        return 0
    if prop_type == "number":
        return 0.0
    if prop_type == "boolean":
        return False
    if prop_type == "array":
        return []
    if prop_type == "object":
        return {}
    return f"<{name}>"


def _extract_body_doc(
    request_body: dict[str, Any],
    full_spec: dict[str, Any],
) -> dict[str, Any]:
    """Extract body schema fields and build an example from OpenAPI requestBody."""
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    schema_name = ""
    if "$ref" in schema:
        ref_path = schema["$ref"]
        schema_name = ref_path.split("/")[-1]
        schema = _resolve_ref(ref_path, full_spec)

    if not schema or schema.get("type") != "object":
        return {"schema_name": schema_name, "fields": [], "example": None}

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    fields: list[dict[str, Any]] = []
    example: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if "$ref" in prop_schema:
            prop_schema = _resolve_ref(prop_schema["$ref"], full_spec)

        prop_type = prop_schema.get("type", "any")
        if prop_type == "array":
            item_type = prop_schema.get("items", {}).get("type", "any")
            prop_type = f"[{item_type}]"

        prop_desc = prop_schema.get("description", prop_schema.get("title", ""))
        prop_default = prop_schema.get("default")
        is_required = prop_name in required_fields

        fields.append({
            "name": prop_name,
            "type": prop_type,
            "required": is_required,
            "description": prop_desc,
            "default": prop_default,
        })

        if is_required:
            example[prop_name] = _example_value(prop_name, prop_schema)

    fields.sort(key=lambda f: (not f["required"], f["name"]))

    return {"schema_name": schema_name, "fields": fields, "example": example}


def generate_operation_script(
    op: dict[str, Any],
    base_url: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str = "",
    full_spec: dict[str, Any] | None = None,
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

    # Header comment — summary + description
    lines.append(f"# {op_name} — {summary}")
    if description:
        lines.append("#")
        for desc_line in _wrap_comment(description, 74):
            lines.append(f"# {desc_line}")

    # Body schema documentation
    has_body = method in ("POST", "PUT", "PATCH") and op.get("request_body")
    if has_body and full_spec:
        body_doc = _extract_body_doc(op["request_body"], full_spec)
        if body_doc["fields"]:
            lines.append("#")
            lines.append(f"# Body schema ({body_doc['schema_name']}):")
            for field in body_doc["fields"]:
                req_marker = " (required)" if field["required"] else ""
                desc_part = f" — {field['description']}" if field["description"] else ""
                default_part = f", default: {field['default']}" if field.get("default") is not None else ""
                lines.append(f"#   {field['name']:<20s} {field['type']:<10s}{req_marker}{desc_part}{default_part}")
            if body_doc["example"]:
                lines.append("#")
                lines.append("# Example:")
                example_json = json.dumps(body_doc["example"], indent=4, ensure_ascii=False)
                example_lines = example_json.split("\n")
                for i, example_line in enumerate(example_lines):
                    if i == 0:
                        lines.append(f"#   ./{op_name}.sh \\")
                    if i == len(example_lines) - 1:
                        lines.append(f"#     '{example_line}'")
                    else:
                        lines.append(f"#     {example_line}")

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
