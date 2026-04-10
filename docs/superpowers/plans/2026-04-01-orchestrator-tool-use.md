# Orchestrator Tool Use — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le parsing JSON manuel de l'orchestrateur par du tool use natif (boucle ReAct).

**Architecture:** L'orchestrateur appelle 4 tools LangChain (`dispatch_agent`, `ask_human`, `human_gate`, `rag_search`) via `llm.bind_tools()`. La boucle ReAct itère jusqu'à une réponse texte ou un tool terminal (`ask_human`, `human_gate`). Le parsing JSON manuel (`parse_llm_decision`) et les modèles associés sont supprimés.

**Tech Stack:** LangChain tools, LangGraph StateGraph, Python 3.11

---

### Task 1: Créer les orchestrator tools

**Files:**
- Create: `Agents/Shared/orchestrator_tools.py`

- [ ] **Step 1: Créer le fichier avec les 4 tools**

```python
"""Orchestrator tools — tools disponibles pour l'orchestrateur."""

import json
import logging
import os
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger("orchestrator")

# Runtime context — set by orchestrator_node before each invocation
_ctx: dict = {}


def set_context(ctx: dict):
    """Set runtime context for tools (thread_id, team_id, allowed_agents, etc.)."""
    global _ctx
    _ctx = ctx


@tool
def dispatch_agent(agent_id: str, task: str) -> str:
    """Dispatche un agent specialise avec une mission precise.
    Utilise ce tool quand un sujet necessite l'expertise d'un agent specifique.
    Args:
        agent_id: Identifiant de l'agent a dispatcher (ex: requirements_analyst, ux_designer)
        task: Description precise de la mission a confier a l'agent
    Returns:
        Confirmation du dispatch ou message d'erreur
    """
    allowed = _ctx.get("allowed_agents", [])
    if allowed and agent_id not in allowed:
        return f"Agent '{agent_id}' non autorise. Agents disponibles : {', '.join(allowed)}"

    # Loop detection
    history = _ctx.get("decision_history", [])
    dispatch_count = sum(
        1 for d in history[-20:]
        for a in d.get("tool_calls", [])
        if a.get("name") == "dispatch_agent" and a.get("args", {}).get("agent_id") == agent_id
    )
    if dispatch_count >= 3:
        return f"Boucle detectee sur {agent_id} (>{dispatch_count} dispatch sans progres). Pose une question a l'utilisateur ou change d'approche."

    # Record dispatch
    dispatched = _ctx.setdefault("agents_dispatched", [])
    dispatched.append({"agent_id": agent_id, "task": task})
    logger.info(f"[orchestrator] dispatch_agent: {agent_id} — {task[:100]}")
    return f"Agent {agent_id} dispatche avec la mission : {task[:200]}"


@tool
def ask_human(message: str) -> str:
    """Pose une question a l'utilisateur et attend sa reponse.
    Utilise ce tool quand tu as besoin d'une clarification, d'un choix,
    ou d'une information que seul l'utilisateur peut fournir.
    Le message peut contenir un bloc (((? ... ))) pour des questions structurees.
    Args:
        message: Le message complet a afficher a l'utilisateur, incluant contexte et questions
    Returns:
        Confirmation que la question a ete posee
    """
    thread_id = _ctx.get("thread_id", "")
    team_id = _ctx.get("team_id", "default")
    project_slug = _ctx.get("project_slug", "")
    task_id = _ctx.get("task_id", "")

    # Create HITL request in DB
    if thread_id.startswith("onboarding-"):
        import psycopg
        db_uri = os.getenv("DATABASE_URI", "")
        if db_uri:
            try:
                with psycopg.connect(db_uri, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO project.hitl_requests
                               (thread_id, agent_id, team_id, request_type, prompt, context, channel, status)
                               VALUES (%s, %s, %s, 'question', %s, %s::jsonb, 'hitl-console', 'pending')
                               RETURNING id""",
                            (thread_id, "orchestrator", team_id, message,
                             json.dumps({"type": "onboarding", "project_slug": project_slug, "task_id": task_id})),
                        )
                        row = cur.fetchone()
                        request_id = str(row[0]) if row else ""
                logger.info(f"[orchestrator] ask_human via HITL: {request_id}")
                _ctx["has_question"] = True
                _ctx["question_request_id"] = request_id
                return f"Question posee a l'utilisateur (request {request_id}). En attente de reponse."
            except Exception as e:
                logger.error(f"[orchestrator] ask_human HITL error: {e}")
                return f"Erreur creation question HITL: {e}"

    # Default: use channel
    from agents.shared.agent_conversation import ask_human_sync
    channel_id = _ctx.get("channel_id", "")
    result = ask_human_sync(
        "Orchestrateur", message, channel_id, "", timeout=1800,
        thread_id=thread_id, team_id=team_id,
    )
    _ctx["has_question"] = True
    if result["answered"]:
        return f"Reponse de {result['author']}: {result['response']}"
    elif result["timed_out"]:
        return "Pas de reponse (timeout). Continue avec ton meilleur jugement."
    else:
        return "Erreur de communication."


@tool
def human_gate(phase: str, next_phase: str) -> str:
    """Demande la validation de l'utilisateur pour transitionner vers la phase suivante.
    Utilise ce tool quand la phase courante est terminee et que le workflow
    autorise la transition.
    Args:
        phase: Nom de la phase courante
        next_phase: Nom de la phase suivante
    Returns:
        Confirmation que la demande de validation a ete creee
    """
    thread_id = _ctx.get("thread_id", "")
    team_id = _ctx.get("team_id", "default")
    project_slug = _ctx.get("project_slug", "")
    task_id = _ctx.get("task_id", "")

    if thread_id.startswith("onboarding-"):
        import psycopg
        db_uri = os.getenv("DATABASE_URI", "")
        if db_uri:
            try:
                with psycopg.connect(db_uri, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO project.hitl_requests
                               (thread_id, agent_id, team_id, request_type, prompt, context, channel, status)
                               VALUES (%s, %s, %s, 'approval', %s, %s::jsonb, 'hitl-console', 'pending')
                               RETURNING id""",
                            (thread_id, "orchestrator", team_id,
                             f"Validation transition : {phase} -> {next_phase}",
                             json.dumps({"type": "phase_validation", "phase": phase,
                                         "next_phase": next_phase, "project_slug": project_slug, "task_id": task_id})),
                        )
                logger.info(f"[orchestrator] human_gate: {phase} -> {next_phase}")
                _ctx["has_question"] = True
                return f"Demande de validation creee : {phase} -> {next_phase}. En attente."
            except Exception as e:
                logger.error(f"[orchestrator] human_gate error: {e}")
                return f"Erreur creation human_gate: {e}"

    # Default: use approval channel
    from agents.shared.human_gate import request_approval_sync
    channel_id = _ctx.get("channel_id", "")
    result = request_approval_sync(
        agent_name="Orchestrateur",
        summary=f"Validation transition : {phase} -> {next_phase}",
        details="",
        channel_id=channel_id,
        team_id=team_id,
    )
    _ctx["has_question"] = True
    return f"{'Approuve' if result.get('approved') else 'Rejete'} par {result.get('reviewer', '?')}"


@tool
def rag_search(query: str, top_k: int = 5) -> str:
    """Recherche dans les documents du projet (base vectorielle RAG).
    Utilise ce tool pour trouver des projets similaires, des templates,
    ou des retours d'experience pertinents.
    Args:
        query: La requete de recherche
        top_k: Nombre de resultats (defaut 5)
    Returns:
        Les passages les plus pertinents des documents du projet
    """
    project_slug = _ctx.get("project_slug", "")
    if not project_slug:
        return "Erreur: pas de projet actif pour la recherche RAG."

    hitl_url = os.getenv("HITL_INTERNAL_URL", "http://langgraph-hitl:8090")
    try:
        import requests as req
        resp = req.post(
            f"{hitl_url}/api/internal/rag/search",
            json={"project_slug": project_slug, "query": query, "top_k": top_k},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
    except Exception as e:
        logger.error(f"[orchestrator] rag_search error: {e}")
        return f"Erreur recherche RAG: {e}"

    if not results:
        return "Aucun resultat trouve dans les documents du projet."

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(
            f"[{i}] ({r.get('filename', '?')} | score: {r.get('score', 0):.2f})\n"
            f"{r.get('content', '')[:500]}"
        )
    return "\n\n---\n\n".join(formatted)


def get_orchestrator_tools() -> list:
    """Retourne la liste des tools de l'orchestrateur."""
    return [dispatch_agent, ask_human, human_gate, rag_search]
```

- [ ] **Step 2: Commit**

```bash
git add Agents/Shared/orchestrator_tools.py
git commit -m "feat: creer les 4 tools de l'orchestrateur (dispatch_agent, ask_human, human_gate, rag_search)"
```

---

### Task 2: Refactorer orchestrator_node en boucle ReAct

**Files:**
- Modify: `Agents/orchestrator.py`

- [ ] **Step 1: Remplacer l'appel LLM + parse_llm_decision par la boucle ReAct**

Dans `orchestrator_node`, remplacer les lignes 428-487 (section `# ── Appel LLM ──` jusqu'à `decision = parse_llm_decision(raw, project_id)`) par :

```python
            # ── Appel LLM avec tools ──
            from agents.shared.rate_limiter import throttled_invoke
            from agents.shared.orchestrator_tools import get_orchestrator_tools, set_context
            from langchain_core.messages import ToolMessage

            override_prompt = ""
            for m in messages:
                role = m[0] if isinstance(m, (list, tuple)) else m.get("role", "")
                content = m[1] if isinstance(m, (list, tuple)) else m.get("content", "")
                if role == "system" and content:
                    override_prompt = content
                    break
            base_prompt = override_prompt or load_system_prompt(team_id)

            # Build context for tools
            tool_ctx = {
                "thread_id": state.get("_thread_id", ""),
                "team_id": team_id,
                "channel_id": state.get("_discord_channel_id", ""),
                "project_slug": state.get("_project_slug", ""),
                "task_id": "",
                "allowed_agents": allowed_agents,
                "decision_history": state.get("decision_history", []),
                "agents_dispatched": [],
                "has_question": False,
            }
            set_context(tool_ctx)

            tools = get_orchestrator_tools()
            llm = get_llm()
            llm_t = llm.bind_tools(tools)

            # Build user message with workflow context
            suggested_ids = [a["agent_id"] for a in suggested_agents]
            if override_prompt:
                agents_list = ', '.join(allowed_agents) if allowed_agents else ', '.join(suggested_ids) or 'aucun'
                constraint = f"\nATTENTION : Tu ne peux dispatcher QUE ces agents : {', '.join(allowed_agents)}. Aucun autre." if allowed_agents else ""
                user_content = (
                    f"Message utilisateur : {last_content[:500]}\n\n"
                    f"Phase : {current_phase}. "
                    f"Agents disponibles : {agents_list}.{constraint}\n"
                )
            else:
                user_content = (
                    f"Contexte du projet :\n"
                    f"```json\n{json.dumps(context, indent=2, default=str)}\n```\n\n"
                    f"Le workflow engine te recommande de dispatcher : "
                    f"{', '.join(a['agent_id'] for a in suggested_agents) or 'aucun'}.\n"
                    f"Phase complete : {'oui' if phase_check['complete'] else 'non'}. "
                    f"Transition possible : {'oui -> ' + transition_check.get('next_phase', '') if transition_check['allowed'] else 'non'}.\n\n"
                    f"IMPORTANT : Respecte les recommandations du workflow engine. "
                    f"Si la phase est complete et la transition possible, utilise human_gate.\n"
                )

            msgs = [
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": user_content},
            ]

            # ReAct loop
            max_iters = 5
            final_text = ""
            from agents.shared.langfuse_setup import get_langfuse_callbacks
            _thread = state.get("_thread_id", "") or config.get("configurable", {}).get("thread_id", "")

            for iteration in range(max_iters):
                use_llm = llm_t
                # Last iteration: strip tools to force text response
                if iteration == max_iters - 1:
                    use_llm = llm
                    logger.info("[orchestrator] ReAct: last iter, stripping tools")

                resp = throttled_invoke(use_llm, msgs, provider_name=CONFIG["llm"],
                                         callbacks=get_langfuse_callbacks(session_id=_thread, trace_name="orchestrator"))
                msgs.append(resp)

                if not resp.tool_calls:
                    final_text = resp.content if isinstance(resp.content, str) else str(resp.content)
                    logger.info(f"[orchestrator] ReAct done — {iteration + 1} iters, text={len(final_text)}c")
                    break

                # Execute tool calls
                for tc in resp.tool_calls:
                    tn, ta = tc["name"], tc["args"]
                    logger.info(f"[orchestrator] Tool: {tn}({json.dumps(ta, default=str)[:200]})")
                    result = "Tool not found"
                    for t in tools:
                        if t.name == tn:
                            try:
                                result = t.invoke(ta)
                                if isinstance(result, (dict, list)):
                                    result = json.dumps(result, ensure_ascii=False, default=str)
                                result = str(result)[:5000]
                            except Exception as e:
                                result = f"Tool error: {e}"
                                logger.error(f"[orchestrator] Tool {tn}: {e}")
                            break
                    msgs.append(ToolMessage(content=result, tool_call_id=tc["id"]))

                    # Terminal tools: stop the loop
                    if tn in ("ask_human", "human_gate"):
                        final_text = ""
                        break

                # If a terminal tool was called, exit the loop
                if tool_ctx.get("has_question"):
                    break
```

- [ ] **Step 2: Remplacer la section post-check (détection boucles, seuil confiance, persistance) par la nouvelle logique**

Remplacer les lignes 489-546 (de `# ── Post-check` jusqu'à `return state`) par :

```python
            # ── Persister les tool calls dans l'historique ──
            history = list(state.get("decision_history", []))
            tool_calls_log = []
            for m in msgs:
                if hasattr(m, "tool_calls") and m.tool_calls:
                    for tc in m.tool_calls:
                        tool_calls_log.append({"name": tc["name"], "args": tc["args"]})
            history.append({
                "tool_calls": tool_calls_log,
                "output": final_text[:500] if final_text else "",
                "has_question": tool_ctx.get("has_question", False),
                "agents_dispatched": [d["agent_id"] for d in tool_ctx.get("agents_dispatched", [])],
            })
            state["decision_history"] = history

            # Update assignments from dispatches
            assignments = dict(state.get("current_assignments", {}))
            for d in tool_ctx.get("agents_dispatched", []):
                assignments[d["agent_id"]] = d["task"][:200]
            state["current_assignments"] = assignments

            # Store output text and dispatch info for gateway
            state["_orchestrator_output"] = final_text
            state["_agents_dispatched"] = [d["agent_id"] for d in tool_ctx.get("agents_dispatched", [])]
            state["_has_question"] = tool_ctx.get("has_question", False)
            state["_dispatched_tasks"] = tool_ctx.get("agents_dispatched", [])

            logger.info(
                f"Decision: tools={[tc['name'] for tc in tool_calls_log]} | "
                f"dispatched={state['_agents_dispatched']} | "
                f"has_question={state['_has_question']}"
            )

            return state

        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            _append_error_decision(state, project_id, f"Erreur interne: {e}")
            return state
```

- [ ] **Step 3: Supprimer le code mort**

Supprimer :
- `parse_llm_decision()` (lignes 169-282)
- Les classes `DecisionType`, `ActionType`, `RoutingAction`, `RoutingDecision` (lignes 36-72)
- Le seuil `confidence_threshold` dans `CONFIG` (ligne 99)
- Le bloc `except json.JSONDecodeError` (ligne 549-552) — plus de parsing JSON

Garder :
- `detect_loop()` (ligne 148) — toujours utilisé par le tool `dispatch_agent`
- `has_critical_legal_alert()` (ligne 161)
- `load_system_prompt()` (ligne 114)
- `_append_error_decision()` (ligne 559) — adapter pour le nouveau format

- [ ] **Step 4: Adapter `_append_error_decision` au nouveau format**

```python
def _append_error_decision(state: dict, project_id: str, error_msg: str):
    """Ajoute une decision d'erreur."""
    history = list(state.get("decision_history", []))
    history.append({
        "tool_calls": [],
        "output": f"Erreur orchestrateur: {error_msg[:200]}",
        "has_question": False,
        "agents_dispatched": [],
        "error": error_msg,
    })
    state["decision_history"] = history
    state["_orchestrator_output"] = f"Erreur orchestrateur: {error_msg[:200]}"
    state["_agents_dispatched"] = []
    state["_has_question"] = False
```

- [ ] **Step 5: Adapter `route_after_orchestrator` au nouveau format**

```python
def route_after_orchestrator(state: dict) -> str:
    """Determine le prochain noeud apres l'orchestrateur."""
    team_id = state.get("_team_id", "team1")
    agent_ids = _load_agent_ids(team_id)

    dispatched = state.get("_agents_dispatched", [])
    has_question = state.get("_has_question", False)

    if has_question:
        return "human_gate"

    for agent_id in dispatched:
        if agent_id in agent_ids:
            return agent_id

    return "end"
```

- [ ] **Step 6: Commit**

```bash
git add Agents/orchestrator.py
git commit -m "refacto: orchestrateur en boucle ReAct avec tool use natif"
```

---

### Task 3: Adapter la gateway

**Files:**
- Modify: `Agents/gateway.py`

- [ ] **Step 1: Adapter la réponse `/invoke` pour lire depuis le state au lieu des decisions JSON**

Dans le endpoint `/invoke`, remplacer le bloc de construction de `output_parts` et `agents_dispatched` (lignes 1260-1311) par :

```python
        # Read results from orchestrator state
        output_text = result.get("_orchestrator_output", "")
        agents_dispatched = result.get("_agents_dispatched", [])
        has_question = result.get("_has_question", False)
        dispatched_tasks = result.get("_dispatched_tasks", [])

        # Build output for display
        output_parts = []
        if output_text:
            output_parts.append(output_text)
        for d in dispatched_tasks:
            output_parts.append(f"⏳ **{d['agent_id']}** : {d['task'][:200]}")
        if agents_dispatched and not output_parts:
            output_parts.append("Agents dispatches.")

        final_output = "\n\n".join(output_parts) if output_parts else "Orchestrateur en attente."

        # Keep backward compat: pass decisions for run_orchestrated
        all_decisions = result.get("decision_history", [])
        decisions = all_decisions[-1:] if all_decisions else []

        if agents_dispatched:
            result["_discord_channel_id"] = channel_id
            background_tasks.add_task(run_orchestrated, result, decisions, channel_id, request.thread_id, canonical_agents)

        return InvokeResponse(
            output=final_output, thread_id=request.thread_id,
            decisions=decisions, agents_dispatched=agents_dispatched)
```

- [ ] **Step 2: Commit**

```bash
git add Agents/gateway.py
git commit -m "refacto: gateway lit les resultats tool use depuis le state orchestrateur"
```

---

### Task 4: Adapter analysis_service

**Files:**
- Modify: `hitl/services/analysis_service.py`

- [ ] **Step 1: Simplifier `_run_analysis_pipeline` — les questions HITL sont créées directement par le tool `ask_human`**

Remplacer le bloc de traitement des decisions (lignes 697-740, le code qu'on a ajouté aujourd'hui pour détecter `escalate_human`) par :

```python
        # Store output as progress event (questions are created by ask_human tool directly)
        output_text = data.get("output", "")
        agents_dispatched = data.get("agents_dispatched", [])
        has_question = any(
            tc.get("name") in ("ask_human", "human_gate")
            for d in data.get("decisions", [])
            for tc in d.get("tool_calls", [])
        )

        if output_text and not has_question:
            await execute(
                """INSERT INTO project.dispatcher_task_events (task_id, event_type, data)
                   VALUES ($1::uuid, 'progress', $2::jsonb)""",
                task_id,
                json.dumps({"data": output_text, "agents_dispatched": agents_dispatched},
                            ensure_ascii=False),
            )

        if has_question:
            await execute(
                "UPDATE project.dispatcher_tasks SET status = 'waiting_input' WHERE id = $1::uuid",
                task_id,
            )
```

- [ ] **Step 2: Commit**

```bash
git add hitl/services/analysis_service.py
git commit -m "refacto: analysis_service simplifie, questions creees par tool ask_human"
```

---

### Task 5: Nettoyage du prompt orchestrateur

**Files:**
- Modify: `Agents/orchestrator.py`

- [ ] **Step 1: Supprimer le format JSON imposé dans le prompt**

Dans `orchestrator_node`, la variable `routing_format` (lignes 440-447) qui ajoutait `--- FORMAT DE SORTIE OBLIGATOIRE ---` doit être supprimée. Le `system_prompt` est maintenant simplement `base_prompt` sans suffix.

Remplacer :
```python
            routing_format = (
                "\n\n--- FORMAT DE SORTIE OBLIGATOIRE ---\n"
                ...
            )
            system_prompt = base_prompt + routing_format if override_prompt else base_prompt
```

Par :
```python
            system_prompt = base_prompt
```

- [ ] **Step 2: Commit**

```bash
git add Agents/orchestrator.py
git commit -m "clean: supprimer le format JSON impose dans le prompt orchestrateur"
```

---

### Task 6: Vérification end-to-end

- [ ] **Step 1: Déployer sur AGT1**

```bash
bash deploy.sh AGT1
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose build --no-cache hitl-console langgraph-api && docker compose up -d hitl-console langgraph-api"
```

- [ ] **Step 2: Purger les threads de test**

```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "docker exec langgraph-postgres psql -U langgraph -d langgraph -c \"DELETE FROM project.rag_conversations WHERE project_slug LIKE '%performance%'; DELETE FROM project.hitl_requests WHERE thread_id LIKE '%performance%'; DELETE FROM checkpoints WHERE thread_id LIKE '%performance%'; DELETE FROM checkpoint_blobs WHERE thread_id LIKE '%performance%'; DELETE FROM checkpoint_writes WHERE thread_id LIKE '%performance%';\""
```

- [ ] **Step 3: Vérifier dans le HITL**

1. Lancer une analyse onboarding
2. Vérifier que l'orchestrateur appelle `rag_search` puis `ask_human` (visible dans Langfuse)
3. Vérifier que la question apparaît dans le chat avec le format `(((? ... )))`
4. Répondre à la question et vérifier que la conversation continue
5. Vérifier que `dispatch_agent` fonctionne (l'orchestrateur dispatche un agent)

- [ ] **Step 4: Vérifier la détection de boucles**

Dans Langfuse, vérifier que si un agent est dispatché 3+ fois sans progrès, le tool retourne un message d'erreur au lieu de dispatcher.
