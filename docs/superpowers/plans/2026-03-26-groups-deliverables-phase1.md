# Groups/Deliverables Refactoring — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `agents` + `deliverables` dicts in workflow phases with a `groups` array containing deliverables directly, simplifying the dispatch model.

**Architecture:** Phases now contain `groups: [{id, deliverables: [...]}]` instead of separate `agents` and `deliverables` blocks. Dispatch is purely sequential by group order (A→B→C). `depends_on` on deliverables is contextual info for agents, not a dispatch constraint. Delegation removed. State output key = `{GROUP}:{deliverable_id}`.

**Tech Stack:** Python 3.11, pytest, vanilla JS (admin editor validation only in Phase 1)

**Spec:** `docs/superpowers/specs/2026-03-26-parallel-groups-refactor-design.md`

---

### Task 1: Update test fixtures to new format

**Files:**
- Modify: `tests/conftest.py:62-147`

- [ ] **Step 1: Replace SAMPLE_WORKFLOW with new groups format**

```python
SAMPLE_WORKFLOW = {
    "phases": {
        "discovery": {
            "name": "Discovery",
            "order": 1,
            "groups": [
                {
                    "id": "A",
                    "deliverables": [
                        {"id": "prd", "Name": "PRD", "agent": "requirements_analyst", "required": True, "type": "specs", "description": "Product Requirements Document", "depends_on": []},
                        {"id": "legal_audit", "Name": "Audit legal", "agent": "legal_advisor", "required": False, "type": "documentation", "description": "Audit legal", "depends_on": []},
                    ],
                },
            ],
            "exit_conditions": {"human_gate": True, "no_critical_alerts": True},
        },
        "design": {
            "name": "Design",
            "order": 2,
            "groups": [
                {
                    "id": "A",
                    "deliverables": [
                        {"id": "wireframes", "Name": "Wireframes", "agent": "ux_designer", "required": True, "type": "design", "description": "Wireframes", "depends_on": []},
                        {"id": "adr", "Name": "ADR", "agent": "architect", "required": True, "type": "specs", "description": "Architecture Decision Records", "depends_on": []},
                    ],
                },
            ],
            "exit_conditions": {"human_gate": False},
        },
        "build": {
            "name": "Build",
            "order": 3,
            "groups": [
                {
                    "id": "A",
                    "deliverables": [
                        {"id": "tech_lead_plan", "Name": "Plan technique", "agent": "lead_dev", "required": True, "type": "specs", "description": "Plan technique du lead dev", "depends_on": []},
                    ],
                },
                {
                    "id": "B",
                    "deliverables": [
                        {"id": "frontend_code", "Name": "Code frontend", "agent": "dev_frontend_web", "required": True, "type": "code", "description": "Code frontend", "depends_on": ["A:tech_lead_plan"]},
                        {"id": "backend_code", "Name": "Code backend", "agent": "dev_backend_api", "required": True, "type": "code", "description": "Code backend", "depends_on": ["A:tech_lead_plan"]},
                    ],
                },
                {
                    "id": "C",
                    "deliverables": [
                        {"id": "test_report", "Name": "Rapport QA", "agent": "qa_engineer", "required": True, "type": "documentation", "description": "Rapport de tests", "depends_on": ["B:frontend_code", "B:backend_code"]},
                    ],
                },
            ],
            "exit_conditions": {},
        },
    },
    "transitions": [
        {"from": "discovery", "to": "design"},
        {"from": "design", "to": "build"},
        {"from": "build", "to": "ship"},
    ],
    "rules": {"max_agents_parallel": 3},
}
```

- [ ] **Step 2: Run existing tests to confirm they fail (old format gone)**

Run: `cd /d E:\srcs\LandGraph && python -m pytest tests/shared/test_workflow_engine.py -v --tb=short 2>&1 | head -50`
Expected: Multiple FAILs (old functions expect `agents` dict)

- [ ] **Step 3: Commit fixture change**

```bash
git add tests/conftest.py
git commit -m "refactor: update SAMPLE_WORKFLOW to groups format"
```

---

### Task 2: Rewrite core helper functions in workflow_engine.py

**Files:**
- Modify: `Agents/Shared/workflow_engine.py:70-106`

- [ ] **Step 1: Rewrite get_phase_agents, get_agents_for_group, get_ordered_groups, get_required_deliverables**

Replace lines 70-91 with:

```python
def get_phase_agents(phase_id: str, team_id: str = "team1") -> dict:
    """Derive agents dict from groups deliverables. Returns {agent_id: {role: agent_id}}."""
    phase = get_phase(phase_id, team_id)
    agents = {}
    for group in phase.get("groups", []):
        for d in group.get("deliverables", []):
            aid = d.get("agent", "")
            if aid and aid not in agents:
                agents[aid] = {"role": aid}
    return agents


def get_agents_for_group(phase_id: str, group: str, team_id: str = "team1") -> list:
    """Return unique agent ids for a given group."""
    phase = get_phase(phase_id, team_id)
    for g in phase.get("groups", []):
        if g.get("id") == group:
            return list(set(d.get("agent", "") for d in g.get("deliverables", []) if d.get("agent")))
    return []


def get_ordered_groups(phase_id: str, team_id: str = "team1") -> list:
    """Return group ids in array order."""
    phase = get_phase(phase_id, team_id)
    return [g.get("id", "") for g in phase.get("groups", [])]


def get_required_deliverables(phase_id: str, team_id: str = "team1") -> list:
    """Return list of output keys (GROUP:id) for required deliverables."""
    phase = get_phase(phase_id, team_id)
    result = []
    for group in phase.get("groups", []):
        gid = group.get("id", "")
        for d in group.get("deliverables", []):
            if d.get("required"):
                result.append(f"{gid}:{d['id']}")
    return result
```

- [ ] **Step 2: Add get_deliverables_for_group helper**

Add after `get_required_deliverables`:

```python
def get_deliverables_for_group(phase_id: str, group_id: str, team_id: str = "team1") -> list:
    """Return deliverable dicts for a given group."""
    phase = get_phase(phase_id, team_id)
    for g in phase.get("groups", []):
        if g.get("id") == group_id:
            return g.get("deliverables", [])
    return []
```

- [ ] **Step 3: Commit**

```bash
git add Agents/Shared/workflow_engine.py
git commit -m "refactor: rewrite helper functions for groups format"
```

---

### Task 3: Rewrite check_phase_complete

**Files:**
- Modify: `Agents/Shared/workflow_engine.py:108-153`

- [ ] **Step 1: Replace check_phase_complete**

```python
def check_phase_complete(phase_id: str, agent_outputs: dict, team_id: str = "team1") -> dict:
    phase = get_phase(phase_id, team_id)
    if not phase:
        return {"complete": False, "missing_agents": [], "missing_deliverables": [],
                "issues": [f"Phase '{phase_id}' inconnue"]}

    missing_deliverables = []
    for group in phase.get("groups", []):
        gid = group.get("id", "")
        for d in group.get("deliverables", []):
            if not d.get("required"):
                continue
            output_key = f"{gid}:{d['id']}"
            output = agent_outputs.get(output_key, {})
            if output and output.get("status") in ("complete", "pending_review", "approved"):
                continue
            missing_deliverables.append(output_key)

    return {
        "complete": not missing_deliverables,
        "missing_agents": [],
        "missing_deliverables": missing_deliverables,
        "issues": [],
    }
```

- [ ] **Step 2: Commit**

```bash
git add Agents/Shared/workflow_engine.py
git commit -m "refactor: check_phase_complete reads groups format"
```

---

### Task 4: Rewrite get_deliverables_to_dispatch

**Files:**
- Modify: `Agents/Shared/workflow_engine.py:224-350`

- [ ] **Step 1: Replace get_deliverables_to_dispatch**

```python
def get_deliverables_to_dispatch(phase_id: str, agent_outputs: dict, team_id: str = "team1") -> list:
    """Return deliverables ready to dispatch. Groups are sequential: A must finish before B starts."""
    phase = get_phase(phase_id, team_id)
    if not phase:
        return []

    groups = phase.get("groups", [])
    if not groups:
        return []

    max_parallel = get_rules(team_id).get("max_agents_parallel", 5)
    to_dispatch = []

    for idx, group in enumerate(groups):
        gid = group.get("id", "")

        # Check all previous groups' required deliverables are done
        prev_done = True
        for prev_group in groups[:idx]:
            pgid = prev_group.get("id", "")
            for d in prev_group.get("deliverables", []):
                if not d.get("required"):
                    continue
                output_key = f"{pgid}:{d['id']}"
                status = agent_outputs.get(output_key, {}).get("status", "")
                if status not in ("complete", "pending_review", "approved"):
                    prev_done = False
                    break
            if not prev_done:
                break
        if not prev_done:
            break

        # Dispatch deliverables in current group that are not yet done
        for d in group.get("deliverables", []):
            output_key = f"{gid}:{d['id']}"
            existing = agent_outputs.get(output_key, {}).get("status", "")
            # Fallback: check disk
            if not existing:
                existing = _check_deliverable_on_disk(d.get("agent", ""), d["id"])
            if existing in ("complete", "pending_review", "approved"):
                continue
            to_dispatch.append({
                "deliverable_key": f"{d.get('agent', '')}:{d['id']}",
                "agent_id": d.get("agent", ""),
                "step": d["id"],
                "parallel_group": gid,
                "required": d.get("required", True),
                "type": d.get("type", ""),
                "description": d.get("description", d["id"]),
            })

        if to_dispatch:
            break  # Only dispatch one group at a time

    return to_dispatch[:max_parallel]
```

- [ ] **Step 2: Commit**

```bash
git add Agents/Shared/workflow_engine.py
git commit -m "refactor: get_deliverables_to_dispatch reads groups format"
```

---

### Task 5: Rewrite get_agents_to_dispatch and get_workflow_status

**Files:**
- Modify: `Agents/Shared/workflow_engine.py:184-221` and `353-385`

- [ ] **Step 1: Replace get_agents_to_dispatch**

```python
def get_agents_to_dispatch(phase_id: str, agent_outputs: dict, team_id: str = "team1") -> list:
    """Derive agents to dispatch from deliverables to dispatch."""
    deliverables = get_deliverables_to_dispatch(phase_id, agent_outputs, team_id)
    seen = set()
    result = []
    for d in deliverables:
        aid = d["agent_id"]
        if aid not in seen:
            seen.add(aid)
            result.append({
                "agent_id": aid,
                "role": aid,
                "required": d.get("required", True),
                "parallel_group": d.get("parallel_group", "A"),
            })
    return result
```

- [ ] **Step 2: Replace get_workflow_status**

```python
def get_workflow_status(current_phase: str, agent_outputs: dict, team_id: str = "team1") -> dict:
    wf = load_workflow(team_id)
    status = {"current_phase": current_phase, "phases": {}}
    for pid, pconf in wf.get("phases", {}).items():
        check = check_phase_complete(pid, agent_outputs, team_id)
        # Build agents status from groups
        agents_status = {}
        for group in pconf.get("groups", []):
            gid = group.get("id", "")
            for d in group.get("deliverables", []):
                aid = d.get("agent", "")
                if aid and aid not in agents_status:
                    output_key = f"{gid}:{d['id']}"
                    output = agent_outputs.get(output_key, {})
                    agents_status[aid] = {
                        "name": aid,
                        "required": d.get("required", False),
                        "status": output.get("status", "pending"),
                        "group": gid,
                    }
        # Build deliverable defs from groups
        deliv_defs = {}
        for group in pconf.get("groups", []):
            gid = group.get("id", "")
            for d in group.get("deliverables", []):
                dk = f"{d.get('agent', '')}:{d['id']}"
                deliv_defs[dk] = {
                    "agent": d.get("agent", ""),
                    "required": d.get("required", False),
                    "type": d.get("type", ""),
                    "description": d.get("description", d["id"]),
                    "step": d["id"],
                    "depends_on": d.get("depends_on", []),
                }
        status["phases"][pid] = {
            "name": pconf.get("name", pid), "order": pconf.get("order", 0),
            "complete": check["complete"], "current": pid == current_phase,
            "agents": agents_status,
            "missing": check.get("missing_agents", []) + check.get("missing_deliverables", []),
            "deliverable_defs": deliv_defs,
        }
    return status
```

- [ ] **Step 3: Commit**

```bash
git add Agents/Shared/workflow_engine.py
git commit -m "refactor: get_agents_to_dispatch and get_workflow_status for groups"
```

---

### Task 6: Rewrite tests

**Files:**
- Modify: `tests/shared/test_workflow_engine.py`

- [ ] **Step 1: Rewrite test classes for new format**

Replace the full file content:

```python
"""Tests pour workflow_engine.py — logique pure, mock load_team_json."""
import pytest
from unittest.mock import patch
from tests.conftest import SAMPLE_WORKFLOW


def _mock_load(team_id, filename):
    if "workflow" in filename.lower():
        return SAMPLE_WORKFLOW
    return {}


@pytest.fixture(autouse=True)
def _patch_loader():
    with patch("Agents.Shared.workflow_engine.load_team_json", side_effect=_mock_load):
        from agents.shared.workflow_engine import _workflows
        _workflows.clear()
        yield


class TestLoadWorkflow:
    def test_loads_workflow(self):
        from agents.shared.workflow_engine import load_workflow
        wf = load_workflow("team1")
        assert "phases" in wf
        assert "discovery" in wf["phases"]

    def test_caches_result(self):
        from agents.shared.workflow_engine import load_workflow, _workflows
        load_workflow("team1")
        assert "team1" in _workflows


class TestGetPhase:
    def test_existing_phase(self):
        from agents.shared.workflow_engine import get_phase
        phase = get_phase("discovery", "team1")
        assert phase["name"] == "Discovery"

    def test_unknown_phase(self):
        from agents.shared.workflow_engine import get_phase
        assert get_phase("nonexistent", "team1") == {}


class TestGetOrderedGroups:
    def test_single_group(self):
        from agents.shared.workflow_engine import get_ordered_groups
        assert get_ordered_groups("discovery", "team1") == ["A"]

    def test_multiple_groups(self):
        from agents.shared.workflow_engine import get_ordered_groups
        assert get_ordered_groups("build", "team1") == ["A", "B", "C"]

    def test_unknown_phase(self):
        from agents.shared.workflow_engine import get_ordered_groups
        assert get_ordered_groups("unknown", "team1") == []


class TestGetAgentsForGroup:
    def test_group_a_discovery(self):
        from agents.shared.workflow_engine import get_agents_for_group
        agents = get_agents_for_group("discovery", "A", "team1")
        assert "requirements_analyst" in agents
        assert "legal_advisor" in agents

    def test_group_b_build(self):
        from agents.shared.workflow_engine import get_agents_for_group
        agents = get_agents_for_group("build", "B", "team1")
        assert "dev_frontend_web" in agents
        assert "dev_backend_api" in agents
        assert "lead_dev" not in agents

    def test_nonexistent_group(self):
        from agents.shared.workflow_engine import get_agents_for_group
        assert get_agents_for_group("discovery", "Z", "team1") == []


class TestGetRequiredDeliverables:
    def test_filters_required(self):
        from agents.shared.workflow_engine import get_required_deliverables
        delivs = get_required_deliverables("discovery", "team1")
        assert "A:prd" in delivs
        assert "A:legal_audit" not in delivs

    def test_all_required(self):
        from agents.shared.workflow_engine import get_required_deliverables
        delivs = get_required_deliverables("design", "team1")
        assert "A:wireframes" in delivs
        assert "A:adr" in delivs


class TestCheckPhaseComplete:
    def test_all_complete(self):
        from agents.shared.workflow_engine import check_phase_complete
        outputs = {"A:prd": {"status": "complete"}}
        result = check_phase_complete("discovery", outputs, "team1")
        assert result["complete"] is True

    def test_missing_required(self):
        from agents.shared.workflow_engine import check_phase_complete
        result = check_phase_complete("discovery", {}, "team1")
        assert result["complete"] is False
        assert "A:prd" in result["missing_deliverables"]

    def test_optional_missing_ok(self):
        from agents.shared.workflow_engine import check_phase_complete
        outputs = {"A:prd": {"status": "complete"}}
        result = check_phase_complete("discovery", outputs, "team1")
        assert result["complete"] is True  # legal_audit is optional

    def test_unknown_phase(self):
        from agents.shared.workflow_engine import check_phase_complete
        result = check_phase_complete("nonexistent", {}, "team1")
        assert result["complete"] is False


class TestCanTransition:
    def _complete_discovery(self):
        return {"A:prd": {"status": "complete"}}

    def test_allowed_when_complete(self):
        from agents.shared.workflow_engine import can_transition
        result = can_transition("discovery", self._complete_discovery(), team_id="team1")
        assert result["allowed"] is True
        assert result["next_phase"] == "design"

    def test_blocked_when_incomplete(self):
        from agents.shared.workflow_engine import can_transition
        result = can_transition("discovery", {}, team_id="team1")
        assert result["allowed"] is False

    def test_human_gate_flag(self):
        from agents.shared.workflow_engine import can_transition
        result = can_transition("discovery", self._complete_discovery(), team_id="team1")
        assert result["needs_human_gate"] is True

    def test_critical_alerts_block(self):
        from agents.shared.workflow_engine import can_transition
        alerts = [{"level": "critical", "resolved": False}]
        result = can_transition("discovery", self._complete_discovery(), legal_alerts=alerts, team_id="team1")
        assert result["allowed"] is False


class TestGetDeliverablesToDispatch:
    def test_dispatches_group_a_first(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        result = get_deliverables_to_dispatch("build", {}, "team1")
        groups = set(r["parallel_group"] for r in result)
        assert groups == {"A"}

    def test_group_b_after_a_complete(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        outputs = {"A:tech_lead_plan": {"status": "complete"}}
        result = get_deliverables_to_dispatch("build", outputs, "team1")
        groups = set(r["parallel_group"] for r in result)
        assert groups == {"B"}
        ids = [r["step"] for r in result]
        assert "frontend_code" in ids
        assert "backend_code" in ids

    def test_group_c_after_b_complete(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        outputs = {
            "A:tech_lead_plan": {"status": "complete"},
            "B:frontend_code": {"status": "complete"},
            "B:backend_code": {"status": "complete"},
        }
        result = get_deliverables_to_dispatch("build", outputs, "team1")
        ids = [r["step"] for r in result]
        assert "test_report" in ids

    def test_blocks_if_prev_group_incomplete(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        outputs = {"A:tech_lead_plan": {"status": "complete"}, "B:frontend_code": {"status": "complete"}}
        # B:backend_code not complete -> C should not dispatch
        result = get_deliverables_to_dispatch("build", outputs, "team1")
        ids = [r["step"] for r in result]
        assert "test_report" not in ids

    def test_skips_already_complete(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        outputs = {"A:prd": {"status": "complete"}, "A:legal_audit": {"status": "complete"}}
        result = get_deliverables_to_dispatch("discovery", outputs, "team1")
        assert result == []

    def test_agent_in_multiple_groups(self):
        """Architect has ADR in A and could have another deliverable in B."""
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        # In the build phase, lead_dev is in A, dev_frontend_web in B
        outputs = {"A:tech_lead_plan": {"status": "complete"}}
        result = get_deliverables_to_dispatch("build", outputs, "team1")
        agent_ids = [r["agent_id"] for r in result]
        assert "dev_frontend_web" in agent_ids
        assert "dev_backend_api" in agent_ids

    def test_empty_for_unknown_phase(self):
        from agents.shared.workflow_engine import get_deliverables_to_dispatch
        assert get_deliverables_to_dispatch("nonexistent", {}, "team1") == []


class TestGetAgentsToDispatch:
    def test_derives_from_deliverables(self):
        from agents.shared.workflow_engine import get_agents_to_dispatch
        result = get_agents_to_dispatch("build", {}, "team1")
        ids = [r["agent_id"] for r in result]
        assert "lead_dev" in ids

    def test_unique_agents(self):
        from agents.shared.workflow_engine import get_agents_to_dispatch
        result = get_agents_to_dispatch("discovery", {}, "team1")
        ids = [r["agent_id"] for r in result]
        assert len(ids) == len(set(ids))


class TestGetWorkflowStatus:
    def test_returns_all_phases(self):
        from agents.shared.workflow_engine import get_workflow_status
        status = get_workflow_status("discovery", {}, "team1")
        assert "discovery" in status["phases"]
        assert "build" in status["phases"]

    def test_current_phase_marked(self):
        from agents.shared.workflow_engine import get_workflow_status
        status = get_workflow_status("discovery", {}, "team1")
        assert status["phases"]["discovery"]["current"] is True
        assert status["phases"]["design"]["current"] is False
```

- [ ] **Step 2: Run tests**

Run: `cd /d E:\srcs\LandGraph && python -m pytest tests/shared/test_workflow_engine.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/shared/test_workflow_engine.py
git commit -m "test: rewrite workflow engine tests for groups format"
```

---

### Task 7: Write migration script

**Files:**
- Create: `migrate_groups.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""Migrate .wrk.json files from agents+deliverables to groups format."""
import json
import os
import sys


def migrate_phase(phase: dict) -> dict:
    """Convert a phase from old format (agents+deliverables) to new (groups)."""
    if phase.get("type") == "external":
        return phase
    # Already migrated?
    if "groups" in phase:
        return phase

    agents = phase.get("agents", {})
    deliverables = phase.get("deliverables", {})

    # 1. Collect groups from agents' parallel_group
    group_map: dict[str, list] = {}
    for agent_id, agent_conf in agents.items():
        gid = agent_conf.get("parallel_group", "A")
        if gid not in group_map:
            group_map[gid] = []

    # Ensure at least group A exists
    if not group_map:
        group_map["A"] = []

    # 2. Distribute deliverables into groups based on their agent
    for dk, dconf in deliverables.items():
        agent_id = dconf.get("agent", "")
        agent_conf = agents.get(agent_id, {})
        gid = agent_conf.get("parallel_group", "A")
        if gid not in group_map:
            group_map[gid] = []

        # Parse old key format: "agent_id:pipeline_step" or just the key
        parts = dk.split(":", 1)
        del_id = parts[1] if len(parts) > 1 else dconf.get("pipeline_step", dk)

        # Convert depends_on from "agent:step" to "GROUP:step"
        new_depends = []
        for dep in dconf.get("depends_on", []):
            dep_parts = dep.split(":", 1)
            if len(dep_parts) == 2:
                dep_agent, dep_step = dep_parts
                dep_agent_conf = agents.get(dep_agent, {})
                dep_gid = dep_agent_conf.get("parallel_group", "A")
                new_depends.append(f"{dep_gid}:{dep_step}")
            else:
                new_depends.append(dep)

        new_del = {
            "id": del_id,
            "Name": dconf.get("name", dconf.get("description", dk)[:60] if dconf.get("description") else dk),
            "agent": agent_id,
            "required": dconf.get("required", True),
            "type": dconf.get("type", ""),
            "description": dconf.get("description", ""),
            "depends_on": new_depends,
        }
        # Preserve optional fields
        for field in ("roles", "missions", "skills", "category"):
            if field in dconf:
                new_del[field] = dconf[field]

        group_map[gid].append(new_del)

    # 3. Build groups array sorted by id
    groups = [{"id": gid, "deliverables": dels}
              for gid, dels in sorted(group_map.items())]

    # 4. Build new phase
    new_phase = {"name": phase.get("name", ""), "order": phase.get("order", 0)}
    if phase.get("description"):
        new_phase["description"] = phase["description"]
    new_phase["groups"] = groups
    new_phase["exit_conditions"] = phase.get("exit_conditions", {})
    if phase.get("next_phase"):
        new_phase["next_phase"] = phase["next_phase"]
    return new_phase


def migrate_workflow(data: dict) -> dict:
    """Migrate a full workflow dict."""
    new_data = {}
    new_phases = {}
    for pid, phase in data.get("phases", {}).items():
        new_phases[pid] = migrate_phase(phase)
    new_data["phases"] = new_phases
    new_data["transitions"] = data.get("transitions", [])
    new_data["rules"] = data.get("rules", {})
    # Keep team, categories if present
    if "team" in data:
        new_data["team"] = data["team"]
    if "categories" in data:
        new_data["categories"] = data["categories"]
    # Remove old parallel_groups root
    return new_data


def migrate_file(filepath: str, dry_run: bool = False) -> bool:
    """Migrate a single .wrk.json file. Returns True if changed."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    migrated = migrate_workflow(data)

    if dry_run:
        print(f"  [DRY RUN] {filepath}")
        print(json.dumps(migrated, indent=2, ensure_ascii=False)[:500])
        return True

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)
    print(f"  [MIGRATED] {filepath}")
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    dirs = sys.argv[1:] if sys.argv[1:] else ["Shared/Projects"]
    dirs = [d for d in dirs if d != "--dry-run"]

    for base_dir in dirs:
        if not os.path.isdir(base_dir):
            print(f"SKIP: {base_dir} not found")
            continue
        for root, _, files in os.walk(base_dir):
            for fname in files:
                if fname.endswith(".wrk.json"):
                    migrate_file(os.path.join(root, fname), dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test with dry-run**

Run: `cd /d E:\srcs\LandGraph && python migrate_groups.py Shared/Projects --dry-run`
Expected: Prints migrated JSON preview for each .wrk.json found

- [ ] **Step 3: Commit**

```bash
git add migrate_groups.py
git commit -m "feat: add migration script for groups format"
```

---

### Task 8: Update validation in admin JS

**Files:**
- Modify: `web/static/js/app.js:10143-10252`

- [ ] **Step 1: Rewrite _wfValidate for groups format**

Replace lines 10143-10252:

```javascript
async function _wfValidate() {
  const errors = [];
  const warnings = [];
  const phases = _wf.data.phases || {};
  const phaseIds = Object.keys(phases);

  // 1. Load agents_registry for this team
  const registryBase = _wf.apiBase.includes('templates') ? '/api/templates/registry' : '/api/agents/registry';
  let registryAgents = new Set();
  try {
    const regDir = _wf.registryDir || _wf.dir;
    const reg = await api(`${registryBase}/${encodeURIComponent(regDir)}`);
    registryAgents = new Set(Object.keys(reg.agents || reg || {}));
  } catch {
    warnings.push('Impossible de charger agents_registry.json — validation des agents ignoree');
  }

  // 2. Validate phases
  for (const [phaseId, phase] of Object.entries(phases)) {
    if (phase.type === 'external') {
      if (!phase.external_workflow) {
        warnings.push('Phase "' + (phase.name || phaseId) + '" : aucun workflow externe configure');
      }
      continue;
    }
    const phaseName = phase.name || phaseId;
    const groups = phase.groups || [];

    // 2a. Phase must have at least one group with a required deliverable
    const hasRequired = groups.some(function(g) {
      return (g.deliverables || []).some(function(d) { return d.required; });
    });
    if (!hasRequired) {
      warnings.push('Phase "' + phaseName + '" : aucun livrable requis');
    }

    // 2b. Validate each group
    const allDeliverableIds = new Set();
    for (const group of groups) {
      const gid = group.id || '';
      for (const d of (group.deliverables || [])) {
        const did = d.id || '';
        const fullKey = gid + ':' + did;

        // Unique id check
        if (allDeliverableIds.has(fullKey)) {
          errors.push('Phase "' + phaseName + '" : livrable "' + fullKey + '" duplique');
        }
        allDeliverableIds.add(fullKey);

        // Agent exists in registry
        if (d.agent && registryAgents.size > 0 && !registryAgents.has(d.agent)) {
          errors.push('Phase "' + phaseName + '" / ' + fullKey + ' : l\'agent "' + d.agent + '" n\'existe pas dans agents_registry.json');
        }

        // depends_on references exist
        for (const dep of (d.depends_on || [])) {
          if (!allDeliverableIds.has(dep)) {
            // Check if it exists in any group (may be defined later in same phase)
            var depFound = false;
            for (const g2 of groups) {
              for (const d2 of (g2.deliverables || [])) {
                if ((g2.id + ':' + d2.id) === dep) { depFound = true; break; }
              }
              if (depFound) break;
            }
            if (!depFound) {
              errors.push('Phase "' + phaseName + '" / ' + fullKey + ' : depends_on "' + dep + '" introuvable');
            }
          }
        }
      }
    }
  }

  // 3. Validate transitions
  for (const t of (_wf.data.transitions || [])) {
    if (t.from && !phaseIds.includes(t.from)) {
      errors.push('Transition : la phase source "' + t.from + '" n\'existe pas');
    }
    if (t.to && !phaseIds.includes(t.to)) {
      errors.push('Transition : la phase cible "' + t.to + '" n\'existe pas');
    }
  }

  return { errors, warnings };
}
```

- [ ] **Step 2: Update cache buster**

In `web/static/index.html`, change `?v=20260326f` to `?v=20260326g` (both CSS and JS references).

- [ ] **Step 3: Commit**

```bash
git add web/static/js/app.js web/static/index.html
git commit -m "refactor: update workflow validation for groups format"
```

---

### Task 9: Run migration on existing workflows

- [ ] **Step 1: Run migration**

Run: `cd /d E:\srcs\LandGraph && python migrate_groups.py Shared/Projects`
Expected: Each .wrk.json file shows `[MIGRATED]`

- [ ] **Step 2: Verify migrated files**

Run: `cd /d E:\srcs\LandGraph && python -c "import json,glob; [print(f) for f in glob.glob('Shared/Projects/**/*.wrk.json', recursive=True)]"`
Then for each file: verify it has `groups` and no `agents`/`deliverables` at phase level.

- [ ] **Step 3: Run all tests**

Run: `cd /d E:\srcs\LandGraph && python -m pytest tests/shared/test_workflow_engine.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit migrated files**

```bash
git add Shared/Projects/
git commit -m "data: migrate workflow files to groups format"
```

---

### Task 10: Update workflow-model.md documentation

**Files:**
- Modify: `docs/workflow-model.md`

- [ ] **Step 1: Update the phase structure section**

Replace the phase structure, agent config, deliverable config, and parallel_groups sections to document the new `groups` format. Key changes:
- Phase has `groups: [{id, deliverables: [...]}]` instead of `agents` + `deliverables`
- Deliverable fields: `id`, `Name`, `description`, `agent`, `required`, `type`, `depends_on` (format `GROUP:ID`, contextual)
- Dispatch: purely sequential by group order
- State output key: `{GROUP}:{deliverable_id}`
- No delegation

- [ ] **Step 2: Commit**

```bash
git add docs/workflow-model.md
git commit -m "docs: update workflow-model.md for groups format"
```
