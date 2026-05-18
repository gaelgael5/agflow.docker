"""Worker provisioning workflow v5 — tranche 2.

Boucle asyncio dans le process FastAPI (lifespan). Poll les project_runtimes
workflow (user_id IS NULL) en status='pending', rend les connection_params
+ setup_steps de chaque instance via Jinja, et marque les statuts.

Si toutes les instances passent à 'ready' → runtime 'deployed'.
Si au moins une 'failed' → runtime 'failed'.
Si au moins une 'pending_setup' (et aucune failed) → runtime 'deployed' aussi
(le contrat v5 §3.4 mappe ça en 'partially_ready' côté DTO, géré par le mapper).
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all
from agflow.services import project_runtime_instances_service as pri_service
from agflow.services.jinja_render import JinjaRenderError, render_jsonb_jinja

_log = structlog.get_logger(__name__)

_POLL_INTERVAL_SECONDS = 5.0


async def process_pending_runtimes() -> None:
    """Une passe : poll + traite tous les runtimes workflow pending."""
    rows = await fetch_all(
        """
        SELECT id, project_id
        FROM project_runtimes
        WHERE status = 'pending'
          AND user_id IS NULL
          AND deleted_at IS NULL
        ORDER BY created_at
        """
    )
    for r in rows:
        try:
            await _provision_runtime_instances(runtime_id=r["id"], project_id=r["project_id"])
        except Exception:
            _log.exception(
                "workflow.provisioning_worker.unexpected_error",
                runtime_id=str(r["id"]),
            )


async def _provision_runtime_instances(
    *, runtime_id: UUID, project_id: UUID
) -> None:
    """Pour chaque pri row du runtime : render Jinja, mark_status."""
    rows = await pri_service.list_by_runtime(project_runtime_id=runtime_id)

    context = _build_jinja_context(runtime_id=runtime_id, project_id=project_id)

    saw_failed = False
    saw_pending_setup = False

    for pri in rows:
        if pri["provisioning_status"] != "provisioning":
            continue  # déjà traité

        # Lire le template connection_params + setup_steps depuis instances
        template_row = await fetch_all(
            """
            SELECT connection_params, setup_steps
            FROM instances
            WHERE id = $1
            """,
            pri["instance_id"],
        )
        if not template_row:
            await pri_service.mark_failed(
                pri_id=pri["id"],
                error_message="template instance row missing",
            )
            saw_failed = True
            continue

        tpl = template_row[0]
        try:
            rendered_params = render_jsonb_jinja(
                tpl["connection_params"] or {}, context
            )
            rendered_steps = render_jsonb_jinja(
                tpl["setup_steps"] or [], context
            )
        except JinjaRenderError as exc:
            await pri_service.mark_failed(
                pri_id=pri["id"], error_message=f"undefined var: {exc}"
            )
            saw_failed = True
            continue

        # Détermine final status :
        # - 'pending_setup' si setup_steps non vide ET tous ont status != 'completed'
        # - 'ready' sinon
        final_status = "ready"
        if isinstance(rendered_steps, list) and rendered_steps:
            non_completed = [
                s for s in rendered_steps
                if isinstance(s, dict) and s.get("status") != "completed"
            ]
            if non_completed:
                final_status = "pending_setup"
                saw_pending_setup = True

        await pri_service.mark_status(
            pri_id=pri["id"],
            status=final_status,
            connection_params=rendered_params,
            setup_steps=rendered_steps if isinstance(rendered_steps, list) else [],
        )

    # Status global du runtime
    final_runtime_status = "failed" if saw_failed else "deployed"

    await execute(
        "UPDATE project_runtimes SET status = $1 WHERE id = $2",
        final_runtime_status,
        runtime_id,
    )
    _log.info(
        "workflow.runtime.provisioning_done",
        runtime_id=str(runtime_id),
        status=final_runtime_status,
        had_pending_setup=saw_pending_setup,
    )


def _build_jinja_context(
    *, runtime_id: UUID, project_id: UUID
) -> dict[str, Any]:
    """Variables disponibles au rendu Jinja.

    V1 minimal : juste les ids. Étendre selon les besoins (machine, network,
    secrets dérivés).
    """
    return {
        "runtime": {
            "id": str(runtime_id),
            "project_id": str(project_id),
            "short_id": str(runtime_id).split("-")[0],
        }
    }


async def run_provisioning_worker_loop(stop_event: asyncio.Event) -> None:
    """Boucle worker — invoquée par lifespan FastAPI avec un stop_event.

    Pattern uniforme avec les autres workers (run_session_idle_reaper_loop,
    run_agent_reaper_loop) : while not stop_event.is_set() + wait_for sur
    stop_event pour permettre une cancellation propre via lifespan shutdown.
    """
    _log.info("workflow.provisioning_worker.started")
    while not stop_event.is_set():
        try:
            await process_pending_runtimes()
        except Exception:
            _log.exception("workflow.provisioning_worker.loop_error")
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=_POLL_INTERVAL_SECONDS
            )
            break  # stop_event was set during wait
        except TimeoutError:
            pass  # interval elapsed, continue loop
    _log.info("workflow.provisioning_worker.stopped")
