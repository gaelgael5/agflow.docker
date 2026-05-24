"""Helpers de résolution d'environnement pour les déploiements.

Ces fonctions sont partagées entre la couche service (deployment_executor)
et la couche API (project_deployments router). Elles n'ont aucune dépendance
sur FastAPI ni sur les routers.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID


def resolve_input_value(raw: str, env_text: str) -> tuple[str, bool]:
    """Resolve ${VAR} references in `raw` against the deploy's .env text.

    Returns (resolved_value, resolved_ok). resolved_ok is False if any reference
    could not be resolved (keeps the literal ${VAR} in the value).
    """
    env_map: dict[str, str] = {}
    for line in (env_text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env_map[k.strip()] = v.strip()

    unresolved = False

    def _repl(match: re.Match) -> str:
        nonlocal unresolved
        key = match.group(1) or match.group(2)
        if key and key in env_map and env_map[key] != "":
            return env_map[key]
        unresolved = True
        return match.group(0)

    # Supports both ${VAR} and $VAR
    resolved = re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)", _repl, raw or "")
    return resolved, not unresolved


async def ssh_kwargs_for_machine(machine_id: UUID) -> dict[str, Any]:
    """Construit les kwargs SSH pour une machine donnée (credentials + cert)."""
    from agflow.services import infra_certificates_service, infra_machines_service

    creds = await infra_machines_service.get_credentials(machine_id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")
    return {
        "host": creds["host"], "port": creds["port"],
        "username": creds["username"], "password": creds["password"],
        "private_key": private_key, "passphrase": passphrase,
    }


def substitute_script_placeholders(script_content: str, input_values: dict[str, str]) -> str:
    """Replace {VAR} placeholders in the script content with input_values[VAR]."""
    out = script_content or ""
    for name, value in (input_values or {}).items():
        out = out.replace(f"{{{name}}}", value)
    return out


def collect_env_from_script(
    link: Any, parsed_json: dict, env_map: dict[str, str],
) -> dict[str, str]:
    """Extract env values from a script's parsed JSON, respecting env_mapping overrides.

    Resolution order for each JSON key:
    1. Explicit mapping in link.env_mapping → target name
    2. Prefixed by group name (uppercased) matching an existing .env var
       (handles the `{GROUP}_VAR` convention used when the recipe scopes
       secrets per group to avoid collisions)
    3. Fallback to the raw JSON key name
    """
    values: dict[str, str] = {}
    mapping = link.env_mapping or {}
    group_name = getattr(link, "group_name", "") or ""
    prefix = (group_name or "").upper().replace("-", "_").replace(" ", "_")
    for json_key, raw_value in parsed_json.items():
        if raw_value is None:
            continue
        value = str(raw_value)
        # 1. Explicit override wins
        if json_key in mapping:
            values[mapping[json_key]] = value
            continue
        # 2. Try `{GROUP}_{json_key}` if it matches an existing env variable
        prefixed = f"{prefix}_{json_key}" if prefix else json_key
        if prefixed in env_map:
            values[prefixed] = value
            continue
        # 3. Fallback to the raw key name
        values[json_key] = value
    return values


def evaluate_trigger_rules(rules: list[Any], env_map: dict[str, str]) -> tuple[bool, str | None]:
    """Return (ok, reason). If any rule fails, ok=False + reason explains which."""
    for r in (rules or []):
        var = getattr(r, "variable", None) if not isinstance(r, dict) else r.get("variable")
        op = getattr(r, "op", None) if not isinstance(r, dict) else r.get("op")
        expected = getattr(r, "value", "") if not isinstance(r, dict) else r.get("value", "")
        if not var:
            continue
        current = env_map.get(var, "")
        if op == "equals":
            if current != expected:
                return False, f"rule failed: {var} != {expected!r} (got {current!r})"
        elif op == "not_equals":
            if current == expected:
                return False, f"rule failed: {var} == {expected!r}"
        elif op == "is_null":
            if current:
                return False, f"rule failed: {var} is not null (got {current!r})"
        else:
            return False, f"unknown operator {op!r}"
    return True, None


def merge_env_with_values(env_text: str, values: dict[str, str]) -> str:
    """For each VAR=... line, if values has VAR, replace the value.

    Any key in `values` that is not already declared in env_text is appended
    at the end so that all script output keys land in the .env.
    """
    out_lines: list[str] = []
    seen_keys: set[str] = set()
    for line in (env_text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        name = line.split("=", 1)[0].strip()
        if name in values:
            out_lines.append(f"{name}={values[name]}")
        else:
            out_lines.append(line)
        seen_keys.add(name)

    # Append keys that weren't already declared
    appended = [k for k in values if k not in seen_keys]
    if appended:
        if out_lines and out_lines[-1].strip() != "":
            out_lines.append("")
        out_lines.append("# Collected from script outputs")
        for k in appended:
            out_lines.append(f"{k}={values[k]}")
    return "\n".join(out_lines)


def parse_env_map(env_text: str) -> dict[str, str]:
    """Parse a .env text into a dict of key=value pairs."""
    env_map: dict[str, str] = {}
    for line in (env_text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env_map[k.strip()] = v.strip()
    return env_map


def parse_last_json(stdout: str) -> dict | None:
    """Find and parse the last JSON line from script stdout."""
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    return None
