"""Mock Docker service — implémentation de référence du contrat v5.

Suffisamment fidèle pour qu'un client (ag.flow workflow) écrive et teste son
code d'intégration sans dépendre d'une vraie implémentation Docker.

État stocké en mémoire (dict). Aucune logique Docker réelle.
Les hooks sont émis via httpx en background avec signature HMAC.

Lance avec :
    uvicorn app:app --port 8080

Variables d'env :
    MOCK_API_KEYS                  Liste séparée par virgules de clés API
                                   acceptées (default: 'agfd_test_key_12345')
    MOCK_HMAC_KEYS                 Liste 'key_id:value' séparée par virgules
                                   (default: 'v1:secret_v1')
    MOCK_RUNTIME_PROVISION_DELAY_S Durée simulée de provisioning runtime
                                   (default: 3 s)
    MOCK_WORK_DURATION_S           Durée simulée d'exécution d'un work
                                   (default: 2 s)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

app = FastAPI(title="Mock Docker service v5", version="5.0.0")
_bearer = HTTPBearer(auto_error=False)


# ── Configuration depuis l'env ─────────────────────────────────────────────


def _env_list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.environ.get(name, default).split(",") if s.strip()]


def _env_hmac_keys() -> dict[str, str]:
    raw = os.environ.get("MOCK_HMAC_KEYS", "v1:secret_v1")
    out: dict[str, str] = {}
    for entry in raw.split(","):
        if ":" not in entry:
            continue
        kid, val = entry.split(":", 1)
        out[kid.strip()] = val.strip()
    return out


VALID_API_KEYS = set(_env_list("MOCK_API_KEYS", "agfd_test_key_12345"))
HMAC_KEYS = _env_hmac_keys()
RUNTIME_PROVISION_DELAY_S = float(os.environ.get("MOCK_RUNTIME_PROVISION_DELAY_S", "3"))
WORK_DURATION_S = float(os.environ.get("MOCK_WORK_DURATION_S", "2"))


# ── Auth middleware ───────────────────────────────────────────────────────


def require_api_key(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Valide la clé API Bearer (RFC 6750 transport schema, pas un JWT)."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": {"code": "missing_token", "message": "Authorization header required"}},
        )
    if creds.credentials not in VALID_API_KEYS:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": {"code": "invalid_token", "message": "Unknown API key"}},
        )
    return creds.credentials


# ── État en mémoire ────────────────────────────────────────────────────────

# Catalogue figé : 2 projets templates
PROJECTS: dict[str, dict[str, Any]] = {
    "11111111-1111-4111-a111-111111111111": {
        "project_id": "11111111-1111-4111-a111-111111111111",
        "name": "Plateforme location vélos",
        "description": "Stack wiki + repo git + RAG pour le métier vélos",
        "resources_summary": [
            {"type": "wiki", "label": "Wiki Outline"},
            {"type": "code_repo", "label": "Repo Git"},
        ],
        "resources_template": [
            {
                "type": "wiki",
                "label": "Wiki Outline",
                "mcp_bindings_preview": [{"name": "wiki", "transport": "stdio"}],
            },
            {
                "type": "code_repo",
                "label": "Repo Git",
                "mcp_bindings_preview": [{"name": "git", "transport": "stdio"}],
            },
        ],
    },
    "22222222-2222-4222-a222-222222222222": {
        "project_id": "22222222-2222-4222-a222-222222222222",
        "name": "Documentation interne",
        "description": "Wiki Outline standalone (pas de repo)",
        "resources_summary": [{"type": "wiki", "label": "Wiki Outline"}],
        "resources_template": [
            {
                "type": "wiki",
                "label": "Wiki Outline",
                "mcp_bindings_preview": [{"name": "wiki", "transport": "stdio"}],
            },
        ],
    },
}

# Runtimes en cours / ready
RUNTIMES: dict[str, dict[str, Any]] = {}
# Resources matérialisées par runtime_id
RUNTIME_RESOURCES: dict[str, list[dict[str, Any]]] = {}
# Sessions
SESSIONS: dict[str, dict[str, Any]] = {}
# Agents par session
SESSION_AGENTS: dict[str, dict[str, dict[str, Any]]] = {}
# Tasks (pour traçabilité)
TASKS: dict[str, dict[str, Any]] = {}


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Pydantic models ────────────────────────────────────────────────────────


class RuntimeCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionCreateBody(BaseModel):
    project_runtime_id: str | None = None
    callback_url: str = Field(min_length=1)
    callback_hmac_key_id: str = Field(min_length=1)
    name: str | None = None
    duration_seconds: int = 3600
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCreateBody(BaseModel):
    slug: str = Field(min_length=1)
    mission: str | None = None


class WorkSubmitBody(BaseModel):
    instruction: dict[str, Any]


# ── Helpers : hook outbound ─────────────────────────────────────────────────


def _sign_hook(secret: str, hook_id: str, timestamp: str, raw_body: bytes) -> str:
    msg = (timestamp + "\n" + hook_id + "\n").encode("utf-8") + raw_body
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"hmac-sha256={sig}"


async def _post_hook(callback_url: str, hmac_key_id: str, payload: dict[str, Any]) -> None:
    """Émet un hook signé HMAC. Best-effort, pas de retry dans le mock."""
    secret = HMAC_KEYS.get(hmac_key_id)
    if not secret:
        print(f"[mock] HMAC key {hmac_key_id!r} unknown, skipping hook")
        return

    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    hook_id = payload["hook_id"]
    timestamp = _now()
    signature = _sign_hook(secret, hook_id, timestamp, raw_body)
    headers = {
        "Content-Type": "application/json",
        "X-Agflow-Hook-Id": hook_id,
        "X-Agflow-Timestamp": timestamp,
        "X-Agflow-Signature": signature,
    }
    full_url = callback_url.rstrip("/") + "/api/v1/hooks/docker/task-completed"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(full_url, content=raw_body, headers=headers)
            print(f"[mock] hook {hook_id} → {full_url} = {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        print(f"[mock] hook {hook_id} failed: {exc}")


# ── Background tasks ────────────────────────────────────────────────────────


async def _provision_runtime(runtime_id: str) -> None:
    """Simule le provisioning des resources du template."""
    await asyncio.sleep(RUNTIME_PROVISION_DELAY_S)

    runtime = RUNTIMES[runtime_id]
    project = PROJECTS[runtime["project_id"]]
    short = runtime_id[:8]

    resources: list[dict[str, Any]] = []
    for tpl in project["resources_template"]:
        rid = _new_uuid()
        if tpl["type"] == "wiki":
            resources.append(
                {
                    "resource_id": rid,
                    "type": "wiki",
                    "status": "ready",
                    "connection_params": {
                        "wiki_url": f"https://outline.{short}.example.com",
                        "api_token_var_name": "OUTLINE_API_TOKEN",
                    },
                    "mcp_bindings": [
                        {
                            "name": "wiki",
                            "transport": "stdio",
                            "command": "npx",
                            "args": ["-y", "@outline/mcp-server"],
                            "env": {
                                "OUTLINE_API_URL": f"https://outline.{short}.example.com",
                                "OUTLINE_API_TOKEN_REF": "${OUTLINE_API_TOKEN}",
                            },
                        }
                    ],
                    "setup_steps": [],
                }
            )
        elif tpl["type"] == "code_repo":
            resources.append(
                {
                    "resource_id": rid,
                    "type": "code_repo",
                    "status": "ready",
                    "connection_params": {
                        "clone_url": f"git@gitlab.{short}.example.com:proj/repo.git",
                        "ssh_key_var_name": "REPO_SSH_KEY",
                    },
                    "mcp_bindings": [
                        {
                            "name": "git",
                            "transport": "stdio",
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-git"],
                            "env": {"REPO_PATH": "/workspace/repo"},
                        }
                    ],
                    "setup_steps": [],
                }
            )

    RUNTIME_RESOURCES[runtime_id] = resources
    runtime["status"] = "ready"
    print(f"[mock] runtime {runtime_id} provisioned ({len(resources)} resources)")


async def _execute_work(
    task_id: str,
    session_id: str,
    agent_uuid: str,
    instruction: dict[str, Any],
) -> None:
    """Simule l'exécution d'un work + émet le hook task-completed."""
    await asyncio.sleep(WORK_DURATION_S)

    session = SESSIONS[session_id]
    agent = SESSION_AGENTS[session_id][agent_uuid]
    started_at = TASKS[task_id]["started_at"]
    completed_at = _now()

    payload = {
        "hook_id": _new_uuid(),
        "task_id": task_id,
        "action_execution_id": instruction.get("_agflow_action_execution_id"),
        "correlation_id": instruction.get("_agflow_correlation_id"),
        "project_runtime_id": session.get("project_runtime_id"),
        "session_id": session_id,
        "agent_uuid": agent_uuid,
        "container_id": f"ctr_{task_id[:8]}",
        "agent_slug": agent["slug"],
        "status": "completed",
        "started_at": started_at,
        "completed_at": completed_at,
        "result": {
            "summary": (
                f"Work simulé par mock — slug={agent['slug']}, "
                f"prompt-len={len(instruction.get('prompt', ''))}"
            ),
            "output_size_bytes": 1024,
            "artifacts": [],
        },
        "error": None,
        "metadata": {"duration_ms": int(WORK_DURATION_S * 1000)},
    }
    TASKS[task_id]["status"] = "completed"
    TASKS[task_id]["completed_at"] = completed_at

    await _post_hook(
        session["callback_url"], session["callback_hmac_key_id"], payload,
    )


# ── Endpoints — orchestration v5 ───────────────────────────────────────────


@app.get("/api/admin/projects", dependencies=[Depends(require_api_key)])
async def list_projects() -> dict[str, list[dict[str, Any]]]:
    return {
        "projects": [
            {k: v for k, v in p.items() if k != "resources_template"}
            for p in PROJECTS.values()
        ],
    }


@app.get("/api/admin/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def get_project(project_id: str) -> dict[str, Any]:
    if project_id not in PROJECTS:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"project {project_id} unknown"}})
    p = PROJECTS[project_id]
    return {
        "project_id": p["project_id"],
        "name": p["name"],
        "description": p["description"],
        "resources": p["resources_template"],
    }


@app.post(
    "/api/admin/projects/{project_id}/runtimes",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def create_runtime(project_id: str, body: RuntimeCreateBody) -> dict[str, Any]:
    if project_id not in PROJECTS:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"project {project_id} unknown"}})

    runtime_id = _new_uuid()
    task_id = _new_uuid()
    now = _now()
    RUNTIMES[runtime_id] = {
        "docker_project_runtime_id": runtime_id,
        "project_id": project_id,
        "name": body.name,
        "metadata": body.metadata,
        "status": "provisioning",
        "created_at": now,
    }
    TASKS[task_id] = {
        "task_id": task_id,
        "kind": "runtime_provision",
        "project_runtime_id": runtime_id,
        "status": "running",
        "started_at": now,
    }
    asyncio.create_task(_provision_runtime(runtime_id))

    return {
        "docker_project_runtime_id": runtime_id,
        "task_id": task_id,
        "status": "provisioning",
        "created_at": now,
    }


@app.get(
    "/api/admin/project-runtimes/{runtime_id}/resources",
    dependencies=[Depends(require_api_key)],
)
async def get_runtime_resources(runtime_id: str) -> dict[str, Any]:
    if runtime_id not in RUNTIMES:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"project_runtime {runtime_id} unknown"}})
    return {
        "docker_project_runtime_id": runtime_id,
        "status": RUNTIMES[runtime_id]["status"],
        "resources": RUNTIME_RESOURCES.get(runtime_id, []),
    }


@app.post(
    "/api/admin/sessions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def create_session(body: SessionCreateBody) -> dict[str, Any]:
    if body.project_runtime_id and body.project_runtime_id not in RUNTIMES:
        raise HTTPException(
            404,
            {"error": {"code": "not_found", "message": f"project_runtime {body.project_runtime_id} unknown"}},
        )
    if body.callback_hmac_key_id not in HMAC_KEYS:
        raise HTTPException(
            400,
            {"error": {"code": "unknown_hmac_key_id", "message": f"key_id {body.callback_hmac_key_id!r} not configured"}},
        )

    session_id = _new_uuid()
    task_id = _new_uuid()
    now = _now()
    expires_at = datetime.now(timezone.utc).timestamp() + body.duration_seconds
    expires_iso = (
        datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    )

    SESSIONS[session_id] = {
        "session_id": session_id,
        "project_runtime_id": body.project_runtime_id,
        "callback_url": body.callback_url,
        "callback_hmac_key_id": body.callback_hmac_key_id,
        "name": body.name,
        "metadata": body.metadata,
        "status": "active",
        "created_at": now,
        "expires_at": expires_iso,
    }
    SESSION_AGENTS[session_id] = {}
    TASKS[task_id] = {
        "task_id": task_id,
        "kind": "session_create",
        "session_id": session_id,
        "status": "completed",
        "started_at": now,
        "completed_at": now,
    }
    return {
        "session_id": session_id,
        "task_id": task_id,
        "project_runtime_id": body.project_runtime_id,
        "status": "active",
        "created_at": now,
        "expires_at": expires_iso,
    }


@app.post(
    "/api/admin/sessions/{session_id}/agents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
)
async def create_agent(session_id: str, body: AgentCreateBody) -> dict[str, Any]:
    if session_id not in SESSIONS:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"session {session_id} unknown"}})
    session = SESSIONS[session_id]
    if session["status"] != "active":
        raise HTTPException(
            409, {"error": {"code": "session_not_active", "message": f"session is {session['status']}"}},
        )

    # Fusion MCP : si project_runtime_id, ajoute mcp_bindings des resources ready
    injected: list[dict[str, Any]] = []
    runtime_id = session.get("project_runtime_id")
    if runtime_id:
        for res in RUNTIME_RESOURCES.get(runtime_id, []):
            if res["status"] != "ready":
                continue
            for binding in res.get("mcp_bindings", []):
                injected.append(
                    {"name": binding["name"], "from_resource_id": res["resource_id"]},
                )

    agent_uuid = _new_uuid()
    task_id = _new_uuid()
    now = _now()
    SESSION_AGENTS[session_id][agent_uuid] = {
        "agent_uuid": agent_uuid,
        "slug": body.slug,
        "session_id": session_id,
        "mission": body.mission,
        "mcp_bindings_injected": injected,
        "status": "ready",
        "created_at": now,
    }
    TASKS[task_id] = {
        "task_id": task_id,
        "kind": "agent_create",
        "session_id": session_id,
        "agent_uuid": agent_uuid,
        "status": "completed",
        "started_at": now,
        "completed_at": now,
    }
    return {
        "agent_uuid": agent_uuid,
        "slug": body.slug,
        "session_id": session_id,
        "task_id": task_id,
        "status": "ready",
        "mcp_bindings_injected": injected,
        "created_at": now,
    }


@app.post(
    "/api/admin/sessions/{session_id}/agents/{agent_uuid}/work",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
async def submit_work(
    session_id: str, agent_uuid: str, body: WorkSubmitBody,
) -> dict[str, Any]:
    if session_id not in SESSIONS:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"session {session_id} unknown"}})
    if SESSIONS[session_id]["status"] != "active":
        raise HTTPException(
            409, {"error": {"code": "session_not_active", "message": "session not active"}},
        )
    if agent_uuid not in SESSION_AGENTS.get(session_id, {}):
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"agent {agent_uuid} not in session"}})

    instruction = body.instruction
    # Validation des champs UUID stricts
    for field in ("_agflow_action_execution_id", "_agflow_correlation_id"):
        val = instruction.get(field)
        if val is None:
            raise HTTPException(
                400,
                {"error": {"code": "missing_field", "message": f"instruction.{field} required"}},
            )
        try:
            uuid.UUID(val, version=4)
        except (ValueError, TypeError):
            raise HTTPException(
                400,
                {"error": {"code": "invalid_uuid", "message": f"instruction.{field} must be UUID v4"}},
            ) from None

    task_id = _new_uuid()
    now = _now()
    TASKS[task_id] = {
        "task_id": task_id,
        "kind": "session_work",
        "session_id": session_id,
        "agent_uuid": agent_uuid,
        "status": "running",
        "started_at": now,
    }
    asyncio.create_task(_execute_work(task_id, session_id, agent_uuid, instruction))

    return {
        "task_id": task_id,
        "session_id": session_id,
        "agent_uuid": agent_uuid,
        "started_at": now,
    }


@app.delete(
    "/api/admin/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
)
async def close_session(session_id: str, force: bool = False) -> None:
    if session_id not in SESSIONS:
        raise HTTPException(404, {"error": {"code": "not_found", "message": f"session {session_id} unknown"}})
    session = SESSIONS[session_id]
    running_tasks = [
        t for t in TASKS.values()
        if t.get("session_id") == session_id
        and t["kind"] == "session_work"
        and t["status"] == "running"
    ]
    if running_tasks and not force:
        raise HTTPException(
            409,
            {
                "error": {
                    "code": "works_in_progress",
                    "message": f"{len(running_tasks)} works still running, use ?force=true",
                },
            },
        )
    session["status"] = "closed"
    for t in running_tasks:
        t["status"] = "cancelled"
        # Hook cancelled
        agent_uuid = t["agent_uuid"]
        agent = SESSION_AGENTS[session_id][agent_uuid]
        payload = {
            "hook_id": _new_uuid(),
            "task_id": t["task_id"],
            "action_execution_id": None,
            "correlation_id": None,
            "project_runtime_id": session.get("project_runtime_id"),
            "session_id": session_id,
            "agent_uuid": agent_uuid,
            "container_id": f"ctr_{t['task_id'][:8]}",
            "agent_slug": agent["slug"],
            "status": "cancelled",
            "started_at": t["started_at"],
            "completed_at": _now(),
            "result": None,
            "error": {"code": "USER_CANCELLED", "message": "force-deleted by ag.flow"},
            "metadata": {},
        }
        asyncio.create_task(
            _post_hook(session["callback_url"], session["callback_hmac_key_id"], payload),
        )


# ── Health ─────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "5.0.0", "type": "mock"}
