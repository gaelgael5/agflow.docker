# Docker Agents — Plan d'implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre aux agents LandGraph de s'executer dans des containers Docker isoles (focus initial : Claude Code), avec gestion du cycle de vie complet : lancement, monitoring stdin/stdout, reconnexion, livrables sur volume, et branchement git par tache.

**Architecture:** Le gateway detecte `docker_mode=true` dans le registry agent et delegue au dispatcher existant (`POST /api/tasks/run`). Le dispatcher lance un container Docker, monte les volumes (workspace git + livrables + config agent), envoie les instructions via stdin, et lit les events sur stdout. Le container reste actif entre les demandes. A la reconnexion, le dispatcher verifie les livrables sur disque plutot que d'interroger l'agent.

**Tech Stack:** Python 3.11, FastAPI, aiodocker, asyncpg, Docker API, bash entrypoints

---

## Architecture des volumes

```
{AG_FLOW_ROOT}/projects/{slug}/
|-- repo/                                          --> /workspace (code, git)
|-- {team_id}/{wf_id}:{workflow}/{phase_id}:{phase_key}/{agent_id}/
|   |-- {deliverable_key}.md                       --> /deliverables/{deliverable_key}.md
|-- .agent-config/{agent_id}/                      --> /agent-config (read-only)
    |-- mcp-packages.txt                           MCP a installer par l'entrypoint
    |-- skills-packages.txt                        Skills a installer
    |-- CLAUDE.md (ou format CLI specifique)        Directives specifiques au CLI
```

## Protocole stdin/stdout

**Entree (stdin)** : JSON une ligne par demande
```json
{
  "task_id": "uuid",
  "agent_id": "requirements_analyst",
  "team_id": "team1",
  "thread_id": "conv-123",
  "phase": "discovery",
  "iteration": 1,
  "payload": {
    "instruction": "Produis le PRD dans /deliverables/prd.md ...",
    "context": {},
    "previous_answers": []
  },
  "timeout_seconds": 600
}
```

**Sortie (stdout)** : JSON une ligne par event
```json
{"task_id":"uuid","type":"progress","data":"Analyse en cours..."}
{"task_id":"uuid","type":"artifact","data":{"key":"prd","content":"...","deliverable_type":"documentation"}}
{"task_id":"uuid","type":"result","data":{"status":"success","exit_code":0,"cost_usd":1.20}}
```

## Resolution des templates run.*.md

Algorithme iteratif (max 10 passes) :
1. Parser `<default>` bloc -> dict `{VAR: valeur}`
2. Appliquer les surcharges `agent.json` -> `docker_env`
3. Remplacer `{VAR}` (PAS `${VAR}`) dans le template `<run type="cmd">`
4. Repeter jusqu'a 0 remplacement

Exemple double resolution (open-code) :
```
Template : -e {API_KEY_NAME}={{API_KEY_NAME}}
Defaults : API_KEY_NAME=ANTHROPIC_API_KEY, ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
Passe 1  : -e ANTHROPIC_API_KEY={ANTHROPIC_API_KEY}
Passe 2  : -e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

## Reconnexion au boot du dispatcher

1. Lister containers `agent-*` via Docker API (label `agflow.task_id`)
2. Pour chaque container actif, chercher la tache en DB par `container_id`
3. Si tache `running` :
   - Verifier le volume livrables sur disque
   - Livrable **code** present (commits sur `temp/{task_id}`) -> termine, avancer workflow
   - Livrable **document** present dans le repertoire -> termine
   - Rien -> re-attacher stdout, reprendre le monitoring
4. Tache en DB mais container mort -> marquer `failure`
5. Container orphelin (pas de tache) -> `stop` + `remove`

**Heartbeat** (toutes les 30 min) : memes verifications sur les taches `running`/`waiting_hitl`

---

## Fichiers concernes

| Fichier | Action | Role |
|---------|--------|------|
| `dispatcher/services/run_template.py` | Creer | Parser run.*.md + resolution iterative des templates |
| `dispatcher/services/workspace_manager.py` | Creer | Preparation volumes (git branch, config agent, livrables) |
| `dispatcher/services/container_watchdog.py` | Creer | Scan boot + heartbeat 30min |
| `dispatcher/services/task_db.py` | Modifier | `build_env()` via templates, `build_volumes()` multi-volumes |
| `dispatcher/services/task_runner.py` | Modifier | Labels Docker, containers persistants, multi-taches |
| `dispatcher/services/docker_manager.py` | Modifier | Ajouter labels, `list_containers()`, `inspect_container()` |
| `dispatcher/core/config.py` | Modifier | Ajouter `watchdog_interval_minutes` |
| `dispatcher/main.py` | Modifier | Lancer watchdog au boot |
| `Agents/gateway.py` | Modifier | Branchement `docker_mode` -> dispatcher |
| `Agents/Shared/agent_loader.py` | Modifier | Exposer la config docker dans l'agent dict |
| `Shared/Dockerfiles/entrypoint.claude-code.sh` | Modifier | permit-all + lecture config volume |
| `web/server.py` | Modifier | Endpoint run-defaults, champ docker_env |
| `web/static/js/app.js` | Modifier | UI docker_env dans Runtime |

---

## Task 1 : Template resolver — `run_template.py`

**Files:**
- Create: `dispatcher/services/run_template.py`
- Test: `dispatcher/tests/test_run_template.py`

- [ ] **Step 1: Write test for `parse_run_md()`**

```python
# dispatcher/tests/test_run_template.py
import pytest
from services.run_template import parse_run_md

SAMPLE_RUN_MD = """
<run type="compose">
  agflow-claude-code:
    image: agflow-claude-code
</run>

<run type="cmd">
docker run -it --rm \\
  -e ANTHROPIC_API_KEY={API_KEY} \\
  -v {WORKSPACE_PATH}:/app \\
  agflow-claude-code
</run>

<default>
\tAPI_KEY =\t${ANTHROPIC_API_KEY}
\tWORKSPACE_PATH = ${WORKSPACE_PATH:-./workspace}
</default>
"""

def test_parse_run_md_extracts_blocks():
    result = parse_run_md(SAMPLE_RUN_MD)
    assert "agflow-claude-code" in result["cmd"]
    assert "agflow-claude-code" in result["compose"]
    assert result["defaults"]["API_KEY"] == "${ANTHROPIC_API_KEY}"
    assert result["defaults"]["WORKSPACE_PATH"] == "${WORKSPACE_PATH:-./workspace}"

def test_parse_run_md_empty():
    result = parse_run_md("")
    assert result["cmd"] == ""
    assert result["compose"] == ""
    assert result["defaults"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dispatcher && python -m pytest tests/test_run_template.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write `parse_run_md()`**

```python
# dispatcher/services/run_template.py
"""Run template resolver — parse run.*.md and resolve {VAR} placeholders."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_RE_RUN_BLOCK = re.compile(r'<run\s+type="(\w+)">\s*\n(.*?)</run>', re.DOTALL)
_RE_DEFAULT_BLOCK = re.compile(r'<default>\s*\n(.*?)</default>', re.DOTALL)
_RE_TEMPLATE_VAR = re.compile(r'(?<!\$)\{([A-Z_][A-Z0-9_]*)\}')
MAX_RESOLVE_PASSES = 10


def parse_run_md(content: str) -> dict:
    """Parse a run.*.md file content.
    Returns {"cmd": str, "compose": str, "defaults": dict}
    """
    result = {"cmd": "", "compose": "", "defaults": {}}
    for m in _RE_RUN_BLOCK.finditer(content):
        block_type = m.group(1).lower()
        if block_type in ("cmd", "compose"):
            result[block_type] = m.group(2).strip()
    dm = _RE_DEFAULT_BLOCK.search(content)
    if dm:
        for line in dm.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            idx = line.find("=")
            if idx >= 0:
                result["defaults"][line[:idx].strip()] = line[idx + 1:].strip()
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dispatcher && python -m pytest tests/test_run_template.py -v`
Expected: PASS

- [ ] **Step 5: Write test for `resolve_template()` — simple case**

```python
# append to dispatcher/tests/test_run_template.py
from services.run_template import resolve_template

def test_resolve_simple():
    template = "docker run -e KEY={API_KEY} image"
    defaults = {"API_KEY": "${ANTHROPIC_API_KEY}"}
    result = resolve_template(template, defaults)
    assert result == "docker run -e KEY=${ANTHROPIC_API_KEY} image"

def test_resolve_no_match():
    template = "docker run image"
    result = resolve_template(template, {})
    assert result == "docker run image"
```

- [ ] **Step 6: Write `resolve_template()`**

```python
# add to dispatcher/services/run_template.py

def resolve_template(
    template: str,
    defaults: dict[str, str],
    overrides: dict[str, str] | None = None,
) -> str:
    """Resolve {VAR} placeholders iteratively.
    overrides (agent.json docker_env) > defaults (run.md <default>).
    ${VAR} is NOT replaced (shell env ref).
    """
    values = dict(defaults)
    if overrides:
        values.update(overrides)
    result = template
    for _ in range(MAX_RESOLVE_PASSES):
        matches = _RE_TEMPLATE_VAR.findall(result)
        if not matches:
            break
        replaced = False
        for var in matches:
            if var in values:
                old = "{" + var + "}"
                new_val = values[var]
                if old in result and new_val != old:
                    result = result.replace(old, new_val)
                    replaced = True
        if not replaced:
            break
    remaining = _RE_TEMPLATE_VAR.findall(result)
    if remaining:
        log.warning("Unresolved template vars: %s", remaining)
    return result
```

- [ ] **Step 7: Run tests**

Run: `cd dispatcher && python -m pytest tests/test_run_template.py -v`
Expected: PASS

- [ ] **Step 8: Write test for double resolution (open-code pattern)**

```python
def test_resolve_double_resolution():
    """open-code pattern: {API_KEY_NAME}={{API_KEY_NAME}} with chained defaults."""
    template = "-e {API_KEY_NAME}={{API_KEY_NAME}}"
    defaults = {
        "API_KEY_NAME": "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
    }
    result = resolve_template(template, defaults)
    # Passe 1: -e ANTHROPIC_API_KEY={ANTHROPIC_API_KEY}
    # Passe 2: -e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    assert result == "-e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"

def test_resolve_with_overrides():
    template = "-e KEY={API_KEY}"
    defaults = {"API_KEY": "${ANTHROPIC_API_KEY}"}
    overrides = {"API_KEY": "${OPENAI_API_KEY}"}
    result = resolve_template(template, defaults, overrides)
    assert result == "-e KEY=${OPENAI_API_KEY}"
```

- [ ] **Step 9: Run tests**

Run: `cd dispatcher && python -m pytest tests/test_run_template.py -v`
Expected: PASS

- [ ] **Step 10: Write `resolve_env_refs()` and `extract_docker_env()`**

```python
# add to dispatcher/services/run_template.py

def resolve_env_refs(value: str) -> str:
    """Resolve ${ENV_VAR} and ${ENV_VAR:-default} from os.environ."""
    def _replace(m):
        expr = m.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.environ.get(var.strip(), default.strip())
        return os.environ.get(expr.strip(), "")
    return re.sub(r'\$\{([^}]+)\}', _replace, value)


def extract_docker_env(cmd_template: str) -> dict[str, str]:
    """Extract -e KEY=VALUE pairs from a resolved docker run command."""
    env = {}
    for m in re.finditer(r'(?:-e|--env)\s+([A-Z_][A-Z0-9_]*)=(\S+)', cmd_template):
        env[m.group(1)] = m.group(2)
    return env


def build_env_from_template(
    run_md_path: str | Path,
    agent_overrides: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Full pipeline: parse run.md -> resolve -> extract env -> resolve ${} refs."""
    path = Path(run_md_path)
    if not path.exists():
        log.warning("run.md not found: %s", path)
        return extra_env or {}
    parsed = parse_run_md(path.read_text(encoding="utf-8"))
    resolved_cmd = resolve_template(parsed["cmd"], parsed["defaults"], agent_overrides)
    env = extract_docker_env(resolved_cmd)
    for k, v in env.items():
        env[k] = resolve_env_refs(v)
    if extra_env:
        env.update(extra_env)
    return env


def get_template_defaults(run_md_path: str | Path) -> dict[str, str]:
    """Read <default> block. Used by admin UI."""
    path = Path(run_md_path)
    if not path.exists():
        return {}
    return parse_run_md(path.read_text(encoding="utf-8"))["defaults"]
```

- [ ] **Step 11: Write test for full pipeline**

```python
import os
from unittest.mock import patch
from services.run_template import build_env_from_template

def test_build_env_full_pipeline(tmp_path):
    run_md = tmp_path / "run.claude-code.md"
    run_md.write_text("""
<run type="cmd">
docker run -e ANTHROPIC_API_KEY={API_KEY} -v {WORKSPACE_PATH}:/app image
</run>
<default>
API_KEY = ${ANTHROPIC_API_KEY}
WORKSPACE_PATH = ${WORKSPACE_PATH:-./workspace}
</default>
""")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-123"}):
        env = build_env_from_template(run_md, extra_env={"AGENT_ROLE": "analyst"})
    assert env["ANTHROPIC_API_KEY"] == "sk-test-123"
    assert env["AGENT_ROLE"] == "analyst"
    assert env["WORKSPACE_PATH"] == "./workspace"
```

- [ ] **Step 12: Run all tests**

Run: `cd dispatcher && python -m pytest tests/test_run_template.py -v`
Expected: ALL PASS

- [ ] **Step 13: Commit**

```bash
git add dispatcher/services/run_template.py dispatcher/tests/test_run_template.py
git commit -m "feat(dispatcher): template resolver for run.*.md — iterative {VAR} resolution"
```

---

## Task 2 : Enrichir `build_env()` et `build_volumes()`

**Files:**
- Modify: `dispatcher/services/task_db.py:117-135`
- Test: `dispatcher/tests/test_task_db.py`

- [ ] **Step 1: Write test for enriched `build_env()`**

```python
# dispatcher/tests/test_task_db.py
import os
from unittest.mock import patch, MagicMock
from models.task import Task, TaskPayload
from services.task_db import build_env, build_volumes

def _make_task(**kw):
    defaults = dict(
        task_id="00000000-0000-0000-0000-000000000001",
        agent_id="test_agent", team_id="team1", thread_id="t-1",
        phase="build", iteration=1,
        payload=TaskPayload(instruction="test"),
        timeout_seconds=300, docker_image="Dockerfile.claude-code",
        project_slug="myproject",
    )
    defaults.update(kw)
    return Task(**defaults)

def test_build_env_fallback():
    """Without run.md, falls back to ANTHROPIC_API_KEY."""
    task = _make_task(docker_image="nonexistent-image")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        env = build_env(task)
    assert env["AGENT_ROLE"] == "test_agent"
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dispatcher && python -m pytest tests/test_task_db.py::test_build_env_fallback -v`
Expected: FAIL (current build_env is hardcoded)

- [ ] **Step 3: Modify `build_env()` in `task_db.py`**

```python
# dispatcher/services/task_db.py — replace build_env() and build_volumes()

def _find_run_md(docker_image: str) -> Optional[str]:
    """Find run.*.md matching a docker image name."""
    name = (docker_image or "").replace("Dockerfile.", "").split(":")[0]
    if name.startswith("agflow-"):
        name = name[len("agflow-"):]
    for base in ["/project/Shared/Dockerfiles", "/app/Shared/Dockerfiles", "Shared/Dockerfiles"]:
        candidate = os.path.join(base, "run.{}.md".format(name))
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_agent_json(agent_id: str) -> dict:
    """Load agent.json from Shared/Agents/{agent_id}/."""
    for base in ["/project/Shared/Agents", "/app/shared_agents", "/app/Shared/Agents", "Shared/Agents"]:
        path = os.path.join(base, agent_id, "agent.json")
        if os.path.isfile(path):
            try:
                return json.loads(open(path, encoding="utf-8").read())
            except Exception:
                pass
    return {}


def build_env(task: Task) -> dict[str, str]:
    """Build env vars via run.md template + agent.json overrides + .env secrets."""
    from services.run_template import build_env_from_template

    extra = {
        "AGENT_ROLE": task.agent_id,
        "AGENT_MAX_TURNS": os.environ.get("AGENT_MAX_TURNS", "10"),
        "AGENT_ALLOWED_TOOLS": os.environ.get(
            "AGENT_ALLOWED_TOOLS",
            "Read,Write,Edit,Bash(git *),Bash(pytest *)",
        ),
    }
    image = task.docker_image or settings.agent_default_image
    run_md = _find_run_md(image)
    if run_md:
        agent_conf = _load_agent_json(task.agent_id)
        overrides = agent_conf.get("docker_env", {})
        return build_env_from_template(run_md, overrides, extra)
    extra["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return extra


def build_volumes(task: Task) -> list[str]:
    """Build volume mounts: workspace + deliverables + agent-config."""
    slug = task.project_slug or "default"
    root = settings.ag_flow_root
    repo = "{}/projects/{}/repo".format(root, slug)
    # Deliverables path: projects/{slug}/{team}/{wf_id}:{workflow}/{phase_id}:{phase}/{agent_id}
    phase = task.phase or "build"
    wf_id = task.workflow_id or 0
    phase_id = getattr(task, "phase_id", 0) or 0
    deliv = "{}/projects/{}/{}/{}:main/{}:{}/{}/".format(
        root, slug, task.team_id, wf_id, phase_id, phase, task.agent_id
    )
    # Agent config
    config = "{}/projects/{}/.agent-config/{}/".format(root, slug, task.agent_id)
    # Ensure directories exist
    import pathlib
    for d in [repo, deliv, config]:
        pathlib.Path(d).mkdir(parents=True, exist_ok=True)
    return [
        "{}:/workspace".format(repo),
        "{}:/deliverables".format(deliv),
        "{}:/agent-config:ro".format(config),
    ]
```

- [ ] **Step 4: Run test**

Run: `cd dispatcher && python -m pytest tests/test_task_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dispatcher/services/task_db.py dispatcher/tests/test_task_db.py
git commit -m "feat(dispatcher): build_env via run.md templates, build_volumes multi-mount"
```

---

## Task 3 : Workspace manager — git branching

**Files:**
- Create: `dispatcher/services/workspace_manager.py`
- Test: `dispatcher/tests/test_workspace_manager.py`

- [ ] **Step 1: Write `workspace_manager.py`**

```python
# dispatcher/services/workspace_manager.py
"""Prepare workspace for a Docker agent task: git branch, config files."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)


def ensure_repo(project_slug: str) -> Path:
    """Ensure the git repo exists at AG_FLOW_ROOT/projects/{slug}/repo."""
    repo = Path(settings.ag_flow_root) / "projects" / project_slug / "repo"
    if not repo.exists():
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "dev"], cwd=str(repo), check=True, capture_output=True)
        log.info("Initialized git repo at %s", repo)
    return repo


def create_task_branch(repo: Path, task_id: str) -> str:
    """Create temp/{task_id} branch from dev. Returns branch name."""
    branch = "temp/{}".format(task_id[:12])
    try:
        subprocess.run(["git", "checkout", "dev"], cwd=str(repo), check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # dev branch may not exist yet
        subprocess.run(["git", "checkout", "-b", "dev"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(repo), check=True, capture_output=True)
    log.info("Created branch %s from dev", branch)
    return branch


def has_commits_on_branch(repo: Path, branch: str) -> bool:
    """Check if branch has commits ahead of dev."""
    try:
        result = subprocess.run(
            ["git", "log", "dev..{}".format(branch), "--oneline"],
            cwd=str(repo), capture_output=True, text=True, check=True,
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def prepare_agent_config(
    project_slug: str,
    agent_id: str,
    agent_json: dict,
    mcp_packages: list[str] | None = None,
    skills_packages: list[str] | None = None,
) -> Path:
    """Write config files into .agent-config/{agent_id}/."""
    config_dir = Path(settings.ag_flow_root) / "projects" / project_slug / ".agent-config" / agent_id
    config_dir.mkdir(parents=True, exist_ok=True)

    # MCP packages
    mcp = mcp_packages or agent_json.get("mcp_access", [])
    if mcp:
        (config_dir / "mcp-packages.txt").write_text("\n".join(mcp) + "\n", encoding="utf-8")

    # Skills packages
    skills = skills_packages or agent_json.get("skills_access", [])
    if skills:
        (config_dir / "skills-packages.txt").write_text("\n".join(skills) + "\n", encoding="utf-8")

    # CLAUDE.md (for Claude Code) — generic: each CLI reads its own format
    docker_image = agent_json.get("docker_image", "")
    if "claude" in docker_image.lower():
        claude_md = "# Agent: {}\n\n".format(agent_json.get("name", agent_id))
        claude_md += "## Regles\n\n"
        claude_md += "- Mode: --dangerously-skip-permissions (permit-all)\n"
        claude_md += "- Ecris les livrables dans /deliverables/\n"
        claude_md += "- Previens quand tu as termine via stdout\n"
        if mcp:
            claude_md += "\n## MCP Servers disponibles\n\n"
            for pkg in mcp:
                claude_md += "- {}\n".format(pkg)
        (config_dir / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    log.info("Agent config prepared at %s", config_dir)
    return config_dir


def check_deliverable_exists(
    project_slug: str,
    team_id: str,
    workflow_id: int,
    phase_id: int,
    phase_key: str,
    agent_id: str,
    deliverable_key: str,
) -> bool:
    """Check if a deliverable file exists on disk."""
    path = (
        Path(settings.ag_flow_root)
        / "projects" / project_slug / team_id
        / "{}:main".format(workflow_id)
        / "{}:{}".format(phase_id, phase_key)
        / agent_id
        / "{}.md".format(deliverable_key)
    )
    return path.exists() and path.stat().st_size > 0
```

- [ ] **Step 2: Write test**

```python
# dispatcher/tests/test_workspace_manager.py
import os
from pathlib import Path
from unittest.mock import patch
from services.workspace_manager import (
    prepare_agent_config,
    check_deliverable_exists,
)

def test_prepare_agent_config_creates_files(tmp_path):
    with patch("services.workspace_manager.settings") as mock_settings:
        mock_settings.ag_flow_root = str(tmp_path)
        config = prepare_agent_config(
            "myproject", "analyst",
            {"name": "Analyst", "docker_image": "Dockerfile.claude-code", "mcp_access": ["git", "memory"]},
        )
    assert (config / "mcp-packages.txt").exists()
    assert "git" in (config / "mcp-packages.txt").read_text()
    assert (config / "CLAUDE.md").exists()
    assert "Analyst" in (config / "CLAUDE.md").read_text()

def test_check_deliverable_exists(tmp_path):
    with patch("services.workspace_manager.settings") as mock_settings:
        mock_settings.ag_flow_root = str(tmp_path)
        # Create deliverable
        d = tmp_path / "projects/proj/team1/0:main/0:discovery/analyst"
        d.mkdir(parents=True)
        (d / "prd.md").write_text("# PRD content")
        assert check_deliverable_exists("proj", "team1", 0, 0, "discovery", "analyst", "prd")
        assert not check_deliverable_exists("proj", "team1", 0, 0, "discovery", "analyst", "missing")
```

- [ ] **Step 3: Run tests**

Run: `cd dispatcher && python -m pytest tests/test_workspace_manager.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dispatcher/services/workspace_manager.py dispatcher/tests/test_workspace_manager.py
git commit -m "feat(dispatcher): workspace manager — git branching + agent config volumes"
```

---

## Task 4 : Container watchdog — boot scan + heartbeat

**Files:**
- Create: `dispatcher/services/container_watchdog.py`
- Modify: `dispatcher/main.py`
- Modify: `dispatcher/core/config.py`

- [ ] **Step 1: Add config setting**

```python
# dispatcher/core/config.py — add to Settings class
watchdog_interval_minutes: int = 30
```

- [ ] **Step 2: Write `container_watchdog.py`**

```python
# dispatcher/services/container_watchdog.py
"""Container watchdog: scan at boot + periodic heartbeat."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import asyncpg

from services.docker_manager import DockerManager
from services.task_db import mark_status, fetch_task
from models.task import TaskStatus
from core.config import settings

log = logging.getLogger(__name__)


class ContainerWatchdog:
    """Scans Docker containers at boot and periodically to reconcile with DB state."""

    def __init__(self, pool: asyncpg.Pool, docker: DockerManager) -> None:
        self._pool = pool
        self._docker = docker
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def scan_once(self) -> None:
        """Run one full reconciliation scan."""
        log.info("Watchdog scan starting")
        docker = await self._docker._get_client()

        # 1. List all agent-* containers
        containers = await docker.containers.list(
            all=True,
            filters={"name": ["agent-"]},
        )
        active_cids = {}
        for c in containers:
            info = await c.show()
            cid = info["Id"]
            state = info["State"]["Status"]  # running, exited, etc.
            labels = info["Config"].get("Labels", {})
            task_id = labels.get("agflow.task_id", "")
            active_cids[cid] = {"state": state, "task_id": task_id, "name": info["Name"]}

        # 2. Check DB tasks with status running/waiting_hitl
        rows = await self._pool.fetch(
            """SELECT id, container_id, status, agent_id, project_slug, phase
               FROM project.dispatcher_tasks
               WHERE status IN ('running', 'waiting_hitl')"""
        )

        for row in rows:
            cid = row["container_id"]
            task_id = row["id"]
            if cid and cid in active_cids:
                cinfo = active_cids.pop(cid)
                if cinfo["state"] == "running":
                    # Container still running — check deliverables on disk
                    log.info("Task %s: container %s still running", task_id, cid[:12])
                    # TODO: check deliverable files + re-attach stdout if needed
                else:
                    # Container exited
                    log.warning("Task %s: container %s exited", task_id, cid[:12])
                    await mark_status(self._pool, task_id, TaskStatus.FAILURE, "Container exited unexpectedly")
                    try:
                        await self._docker.remove_container(cid)
                    except Exception:
                        pass
            elif cid:
                # Container not found — mark failure
                log.warning("Task %s: container %s not found", task_id, cid[:12])
                await mark_status(self._pool, task_id, TaskStatus.FAILURE, "Container disappeared")

        # 3. Orphan containers (active but no DB task)
        for cid, cinfo in active_cids.items():
            log.warning("Orphan container %s (%s) — removing", cinfo["name"], cid[:12])
            try:
                await self._docker.stop_container(cid, timeout=5)
                await self._docker.remove_container(cid)
            except Exception as e:
                log.error("Failed to remove orphan: %s", e)

        log.info("Watchdog scan complete")

    async def start(self) -> None:
        """Start periodic heartbeat."""
        self._running = True
        # Initial scan
        await self.scan_once()
        # Start periodic loop
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop the heartbeat."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        """Run scan every N minutes."""
        interval = settings.watchdog_interval_minutes * 60
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            try:
                await self.scan_once()
            except Exception as e:
                log.exception("Watchdog heartbeat error: %s", e)
```

- [ ] **Step 3: Wire into `dispatcher/main.py`**

```python
# Add to dispatcher/main.py lifespan():

# After _task_runner creation:
from services.container_watchdog import ContainerWatchdog
_watchdog = ContainerWatchdog(pool, _docker_manager)
await _watchdog.start()

# Before cleanup:
if _watchdog:
    await _watchdog.stop()
```

- [ ] **Step 4: Commit**

```bash
git add dispatcher/services/container_watchdog.py dispatcher/main.py dispatcher/core/config.py
git commit -m "feat(dispatcher): container watchdog — boot scan + 30min heartbeat"
```

---

## Task 5 : Labels Docker + containers persistants

**Files:**
- Modify: `dispatcher/services/docker_manager.py:33-71`
- Modify: `dispatcher/services/task_runner.py:107-141`

- [ ] **Step 1: Add labels to `create_container()`**

```python
# dispatcher/services/docker_manager.py — modify create_container()
# Add parameter:
#   labels: dict[str, str] | None = None
# Add to config dict:
#   "Labels": labels or {},

async def create_container(
    self,
    image: str,
    env: dict[str, str],
    volumes: list[str],
    mem_limit: str = "",
    cpu_quota: int = 0,
    name: Optional[str] = None,
    network: Optional[str] = None,
    labels: dict[str, str] | None = None,
) -> str:
    # ... existing code ...
    config: dict[str, Any] = {
        "Image": image,
        "Env": [f"{k}={v}" for k, v in env.items()],
        "Labels": labels or {},
        "OpenStdin": True,
        "StdinOnce": False,  # Changed: keep stdin open for multi-task
        "Tty": False,
        "HostConfig": host_config,
    }
    # ... rest unchanged ...
```

- [ ] **Step 2: Add `list_agent_containers()` to DockerManager**

```python
async def list_agent_containers(self) -> list[dict]:
    """List all agent-* containers with their labels and state."""
    docker = await self._get_client()
    containers = await docker.containers.list(all=True, filters={"name": ["agent-"]})
    result = []
    for c in containers:
        info = await c.show()
        result.append({
            "id": info["Id"],
            "name": info["Name"].lstrip("/"),
            "state": info["State"]["Status"],
            "labels": info["Config"].get("Labels", {}),
        })
    return result
```

- [ ] **Step 3: Pass labels in `task_runner.py:_execute()`**

```python
# In _execute(), add labels to managed_container call:
labels = {
    "agflow.task_id": str(task.task_id),
    "agflow.agent_id": task.agent_id,
    "agflow.team_id": task.team_id,
    "agflow.project": task.project_slug or "",
}

async with self._docker.managed_container(
    image=image, env=env, volumes=volumes,
    mem_limit=settings.agent_mem_limit,
    cpu_quota=settings.agent_cpu_quota,
    name=f"agent-{task.agent_id}-{str(task.task_id)[:8]}",
    network=network,
    labels=labels,
) as container_id:
```

- [ ] **Step 4: Update `managed_container()` to accept labels**

```python
@asynccontextmanager
async def managed_container(
    self, image, env, volumes,
    mem_limit="", cpu_quota=0, name=None, network=None,
    labels=None,  # <-- add
) -> AsyncIterator[str]:
    container_id = await self.create_container(
        image=image, env=env, volumes=volumes,
        mem_limit=mem_limit, cpu_quota=cpu_quota,
        name=name, network=network, labels=labels,  # <-- pass
    )
    # ... rest unchanged ...
```

- [ ] **Step 5: Commit**

```bash
git add dispatcher/services/docker_manager.py dispatcher/services/task_runner.py
git commit -m "feat(dispatcher): Docker labels agflow.task_id/agent_id + StdinOnce=False"
```

---

## Task 6 : Branchement Gateway -> Dispatcher

**Files:**
- Modify: `Agents/gateway.py:252-323`
- Modify: `Agents/Shared/agent_loader.py:21-37`

- [ ] **Step 1: Expose docker config in agent_loader**

```python
# Agents/Shared/agent_loader.py — modify _create_agent()
# Add docker_mode and docker_image to attrs:

def _create_agent(agent_id, conf, has_mcp, team_id="default"):
    use_tools = conf.get("use_tools", has_mcp)
    attrs = {
        "agent_id": agent_id,
        "agent_name": conf.get("name", agent_id),
        "default_llm": conf.get("llm", ""),
        "default_model": conf.get("model", "claude-sonnet-4-5-20250929"),
        "default_temperature": conf.get("temperature", 0.3),
        "default_max_tokens": conf.get("max_tokens", 32768),
        "prompt_filename": conf.get("prompt", f"{agent_id}.md"),
        "steps": conf.get("steps", []),
        "use_tools": use_tools,
        "requires_approval": conf.get("requires_approval", False),
        "team_id": team_id,
        "docker_mode": conf.get("docker_mode", False),
        "docker_image": conf.get("docker_image", ""),
    }
    AgentClass = type(f"Agent_{agent_id}", (BaseAgent,), attrs)
    return AgentClass()
```

- [ ] **Step 2: Add `dispatch_to_docker()` in gateway.py**

```python
# Agents/gateway.py — add after run_single_agent()

DISPATCHER_URL = os.getenv("DISPATCHER_URL", "http://langgraph-dispatcher:8070")

async def dispatch_to_docker(agent_id, agent_callable, state, channel_id, thread_id=""):
    """Dispatch an agent task to the Docker dispatcher instead of running in-process."""
    import httpx

    team_id = state.get("_team_id", "default")
    slug = state.get("project_slug", state.get("_project_slug", "default"))
    phase = state.get("project_phase", "build")
    workflow_id = state.get("_workflow_id")

    # Build instruction from BaseAgent prompt composition
    instruction = ""
    task_info = state.get("_deliverable_dispatch", {})
    if task_info:
        instruction = task_info.get("instruction", "")
    if not instruction:
        # Extract from decision history
        for d in reversed(state.get("decision_history", [])):
            for tc in d.get("tool_calls", []):
                if tc.get("target") == agent_id:
                    instruction = tc.get("task", "")
                    break
            if instruction:
                break

    if not instruction:
        instruction = "Execute ta mission selon ton prompt systeme."

    payload = {
        "agent_id": agent_id,
        "team_id": team_id,
        "thread_id": thread_id,
        "project_slug": slug,
        "phase": phase,
        "iteration": state.get("_iteration", 1),
        "payload": {
            "instruction": instruction,
            "context": {
                "project_metadata": state.get("project_metadata", {}),
                "existing_outputs": list(state.get("agent_outputs", {}).keys()),
            },
            "previous_answers": [],
        },
        "timeout_seconds": 1800,  # 30 min
        "docker_image": getattr(agent_callable, "docker_image", ""),
    }
    if workflow_id:
        payload["workflow_id"] = workflow_id

    logger.info("[docker] Dispatching %s to dispatcher", agent_id)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post("{}/api/tasks/run".format(DISPATCHER_URL), json=payload)
            resp.raise_for_status()
            data = resp.json()
            task_id = data["task_id"]
            logger.info("[docker] Task created: %s for agent %s", task_id, agent_id)
    except Exception as e:
        logger.error("[docker] Failed to dispatch %s: %s", agent_id, e)
        await post_to_channel(channel_id, "Erreur dispatch Docker {}: {}".format(agent_id, str(e)[:200]), thread_id)
        return state

    # Poll for completion
    await _poll_docker_task(task_id, agent_id, state, channel_id, thread_id)
    return state


async def _poll_docker_task(task_id, agent_id, state, channel_id, thread_id, interval=10, max_wait=1800):
    """Poll dispatcher for task completion."""
    import httpx

    elapsed = 0
    while elapsed < max_wait:
        await asyncio.sleep(interval)
        elapsed += interval
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("{}/api/tasks/{}".format(DISPATCHER_URL, task_id))
                data = resp.json()
                status = data.get("status", "")
                if status in ("success", "failure", "timeout", "cancelled"):
                    logger.info("[docker] Task %s finished: %s", task_id, status)
                    if status == "success":
                        # Inject result into agent_outputs
                        ao = dict(state.get("agent_outputs", {}))
                        ao[agent_id] = {
                            "agent_id": agent_id,
                            "status": "complete",
                            "confidence": 0.8,
                            "deliverables": {},
                            "docker_task_id": task_id,
                        }
                        # Load artifacts as deliverables
                        for art in data.get("artifacts", []):
                            ao[agent_id]["deliverables"][art["key"]] = "(voir fichier sur disque)"
                        state["agent_outputs"] = ao
                    else:
                        err = data.get("error_message", "Unknown error")
                        await post_to_channel(channel_id, "Docker {} echoue: {}".format(agent_id, err[:300]), thread_id)
                    return
        except Exception as e:
            logger.warning("[docker] Poll error for %s: %s", task_id, e)
    logger.error("[docker] Task %s timed out after %ds", task_id, max_wait)
    await post_to_channel(channel_id, "Docker {} timeout ({}s)".format(agent_id, max_wait), thread_id)
```

- [ ] **Step 3: Modify `run_single_agent()` to branch on docker_mode**

```python
# Agents/gateway.py — modify run_single_agent() at line ~253
# Add at the beginning of the try block:

async def run_single_agent(agent_id, agent_callable, state, channel_id, thread_id=""):
    try:
        # Docker mode: delegate to dispatcher
        if getattr(agent_callable, "docker_mode", False):
            return await dispatch_to_docker(agent_id, agent_callable, state, channel_id, thread_id)

        # Standard in-process execution
        result = await asyncio.wait_for(
            asyncio.to_thread(agent_callable, dict(state)), timeout=2100)
        # ... rest unchanged ...
```

- [ ] **Step 4: Commit**

```bash
git add Agents/gateway.py Agents/Shared/agent_loader.py
git commit -m "feat(gateway): branch docker_mode agents to dispatcher REST API"
```

---

## Task 7 : Entrypoint Claude Code — permit-all + config volume

**Files:**
- Modify: `Shared/Dockerfiles/entrypoint.claude-code.sh`

- [ ] **Step 1: Rewrite entrypoint**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Read task from stdin ──
TASK_JSON=$(cat)
TASK_ID=$(echo "$TASK_JSON"    | jq -r '.task_id')
INSTRUCTION=$(echo "$TASK_JSON" | jq -r '.payload.instruction')
TIMEOUT=$(echo "$TASK_JSON"    | jq -r '.timeout_seconds // 600')

emit_event() {
    local type=$1
    local data=$2
    echo "{\"task_id\":\"$TASK_ID\",\"type\":\"$type\",\"data\":$data}"
}

# ── Install MCP packages from config volume ──
if [ -f /agent-config/mcp-packages.txt ]; then
    emit_event "progress" "\"Installation des MCP packages...\""
    while IFS= read -r pkg; do
        [ -z "$pkg" ] && continue
        claude mcp add-from-registry "$pkg" 2>/dev/null || true
    done < /agent-config/mcp-packages.txt
fi

# ── Copy CLAUDE.md to workspace if exists ──
if [ -f /agent-config/CLAUDE.md ]; then
    cp /agent-config/CLAUDE.md /workspace/CLAUDE.md 2>/dev/null || true
fi

emit_event "progress" "\"Agent $AGENT_ROLE demarre — tache $TASK_ID\""

# ── Execute Claude Code in permit-all mode ──
EXIT_CODE=0
cd /workspace
RESULT=$(timeout "$TIMEOUT" claude \
    -p "$INSTRUCTION" \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --max-turns "${AGENT_MAX_TURNS:-10}" \
    2>/dev/null) || EXIT_CODE=$?

# ── Parse and emit events ──
echo "$RESULT" | while IFS= read -r line; do
    TYPE=$(echo "$line" | jq -r '.type // empty')
    case "$TYPE" in
        "assistant")
            TEXT=$(echo "$line" | jq -c '.message.content[]? | select(.type=="text") | .text')
            [ -n "$TEXT" ] && emit_event "progress" "$TEXT"
            ;;
        "tool_use")
            TOOL=$(echo "$line" | jq -c '{tool: .name, input: .input}')
            emit_event "artifact" "$TOOL"
            ;;
        "result")
            COST=$(echo "$line" | jq -r '.cost_usd // 0')
            emit_event "progress" "\"cost_usd: $COST\""
            ;;
    esac
done

if [ "$EXIT_CODE" -eq 0 ]; then
    emit_event "result" "{\"status\":\"success\",\"exit_code\":0}"
else
    emit_event "result" "{\"status\":\"failure\",\"exit_code\":$EXIT_CODE}"
fi

exit $EXIT_CODE
```

- [ ] **Step 2: Commit**

```bash
git add Shared/Dockerfiles/entrypoint.claude-code.sh
git commit -m "feat(docker): Claude Code entrypoint — permit-all + MCP install from volume"
```

---

## Task 8 : Dashboard admin — docker_env editable

**Files:**
- Modify: `web/server.py` (endpoint run-defaults, champ docker_env)
- Modify: `web/static/js/app.js` (UI Runtime tab)

- [ ] **Step 1: Add `docker_env` to agent schema and save**

Deja fait dans les modifications precedentes (MCPCatalogEntry + _update_agent).

- [ ] **Step 2: Add UI for docker_env in Runtime tab**

Le code JS pour `_saLoadDockerDefaults()`, `_saRenderDockerEnvTable()`, `_saGetDockerEnv()` est deja ecrit.

- [ ] **Step 3: Wire `docker_env` into save**

```python
# Ensure saveSharedAgent() reads _saGetDockerEnv() and passes it:
# Already done: docker_env is in the model and the save loop.
```

- [ ] **Step 4: Commit**

```bash
git add web/server.py web/static/js/app.js web/static/index.html
git commit -m "feat(admin): docker_env editable in agent Runtime tab"
```

---

## Verification E2E

### Test minimal

1. Configurer `requirements_analyst` avec `docker_mode: true`, `docker_image: "Dockerfile.claude-code"` (deja fait)
2. Builder l'image sur le serveur :
   ```bash
   ssh root@192.168.10.147 "cd /root/tests/lang/Shared/Dockerfiles && docker build -f Dockerfile.claude-code -t agflow-claude-code:latest ."
   ```
3. Creer un projet test avec repo git :
   ```bash
   ssh root@192.168.10.147 "mkdir -p /root/ag.flow/projects/test-docker/repo && cd /root/ag.flow/projects/test-docker/repo && git init && git checkout -b dev"
   ```
4. Envoyer une tache via curl :
   ```bash
   curl -X POST http://192.168.10.147:8070/api/tasks/run -H 'Content-Type: application/json' -d '{
     "agent_id": "requirements_analyst",
     "team_id": "team1",
     "thread_id": "test-docker-1",
     "project_slug": "test-docker",
     "phase": "discovery",
     "payload": {"instruction": "Cree un fichier /deliverables/prd.md avec un PRD minimal"},
     "timeout_seconds": 120
   }'
   ```
5. Verifier :
   - Container `agent-requirements_analyst-*` actif : `docker ps`
   - Events en DB : `SELECT * FROM project.dispatcher_task_events ORDER BY created_at DESC LIMIT 10`
   - Livrable sur disque : `ls /root/ag.flow/projects/test-docker/team1/0:main/0:discovery/requirements_analyst/`
6. Tuer le dispatcher, verifier que le container continue
7. Redemarrer, verifier le scan watchdog dans les logs
