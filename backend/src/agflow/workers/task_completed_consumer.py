"""Worker consumer MOM : détection de fin de work agent → enqueue hook.

Consumer group 'workflow_task_completed' qui claim les agent_messages OUT
de kind=result ou kind=error contenant un _agflow_task_id dans payload.
Pour chaque message :
  1. UPDATE tasks SET status='completed'/'failed' + result/error
  2. Si session.callback_url non null → INSERT outbound_hooks (pending)
  3. Ack le message
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import fetch_one, get_pool
from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction, Envelope, Kind
from agflow.services import (
    hook_payload_builder,
    outbound_hooks_service,
    tasks_service,
)

_log = structlog.get_logger(__name__)

_CONSUMER_GROUP = "workflow_task_completed"
_DEFAULT_INTERVAL_S = 2.0


async def process_batch() -> None:
    """Une passe : claim + traite + ack une batch de messages OUT."""
    pool = await get_pool()
    consumer = MomConsumer(
        pool=pool,
        group_name=_CONSUMER_GROUP,
        consumer_id=f"workflow-consumer-{uuid4()}",
    )
    envelopes = await consumer.claim_batch(direction=Direction.OUT, batch_size=20)
    for env in envelopes:
        try:
            await _process_envelope(env)
            await consumer.ack(env.msg_id)
        except Exception as exc:
            await consumer.fail(env.msg_id, error=str(exc))
            _log.exception(
                "workflow.task_completed_consumer.process_failed",
                msg_id=env.msg_id,
            )


async def _process_envelope(env: Envelope) -> None:
    payload = env.payload or {}
    raw_task_id = payload.get("_agflow_task_id")
    if not raw_task_id:
        # Message non-workflow (résultat M5 classique) → ack sans effet
        return

    try:
        task_id = UUID(str(raw_task_id))
    except (ValueError, TypeError):
        _log.warning(
            "workflow.task_completed_consumer.invalid_task_id",
            raw_task_id=raw_task_id,
            msg_id=env.msg_id,
        )
        return

    # 1) Update tasks lifecycle
    if env.kind == Kind.RESULT:
        result = payload.get("result", {})
        try:
            await tasks_service.mark_completed(task_id=task_id, result=result)
        except tasks_service.TaskNotFoundError:
            _log.warning(
                "workflow.task_completed_consumer.task_not_found",
                task_id=str(task_id),
                msg_id=env.msg_id,
            )
            return
        status = "completed"
    elif env.kind == Kind.ERROR:
        error = payload.get("error", {"code": "UNKNOWN", "message": "no error info"})
        try:
            await tasks_service.mark_failed(task_id=task_id, error=error)
        except tasks_service.TaskNotFoundError:
            _log.warning(
                "workflow.task_completed_consumer.task_not_found",
                task_id=str(task_id),
                msg_id=env.msg_id,
            )
            return
        status = "failed"
    else:
        return  # cas non couvert

    # 2) Look up session + agent + runtime pour construire le hook
    row = await fetch_one(
        """
        SELECT
            t.id AS task_id,
            t.agflow_action_execution_id,
            t.agflow_correlation_id,
            t.project_runtime_id,
            t.session_id,
            t.agent_instance_id,
            t.started_at,
            t.completed_at,
            t.result,
            t.error,
            s.callback_url,
            s.callback_hmac_key_id,
            ai.agent_id AS agent_slug,
            ai.last_container_name AS container_id
        FROM tasks t
        LEFT JOIN sessions s ON s.id = t.session_id
        LEFT JOIN agents_instances ai ON ai.id = t.agent_instance_id
        WHERE t.id = $1
        """,
        task_id,
    )
    if row is None or not row["callback_url"]:
        _log.info(
            "workflow.task_completed.no_callback",
            task_id=str(task_id),
        )
        return  # session sans callback → on ne hook pas

    # 3) Idempotence : si un hook existe déjà pour ce task_id, skip
    existing = await fetch_one(
        "SELECT hook_id FROM outbound_hooks WHERE task_id = $1",
        task_id,
    )
    if existing is not None:
        _log.info(
            "workflow.task_completed.hook_already_exists",
            task_id=str(task_id),
            existing_hook_id=str(existing["hook_id"]),
        )
        return

    # Validate required _agflow_* fields are present in the task row
    action_exec_id = row["agflow_action_execution_id"]
    corr_id = row["agflow_correlation_id"]
    if action_exec_id is None or corr_id is None:
        _log.error(
            "workflow.task_completed.missing_agflow_ids",
            task_id=str(task_id),
            action_execution_id=str(action_exec_id) if action_exec_id else None,
            correlation_id=str(corr_id) if corr_id else None,
        )
        raise RuntimeError(
            f"task {task_id} is missing _agflow_action_execution_id or "
            f"_agflow_correlation_id (data bug upstream)"
        )

    hook_id = uuid4()
    payload_body = hook_payload_builder.build_task_completed_payload(
        hook_id=hook_id,
        task_id=task_id,
        action_execution_id=action_exec_id,
        correlation_id=corr_id,
        project_runtime_id=row["project_runtime_id"],
        session_id=row["session_id"],
        agent_uuid=row["agent_instance_id"],
        agent_slug=row["agent_slug"] or "",
        container_id=row["container_id"],
        status=status,
        started_at=row["started_at"] or datetime.now(UTC),
        completed_at=row["completed_at"] or datetime.now(UTC),
        result=row["result"],
        error=row["error"],
        metadata={},
    )

    await outbound_hooks_service.enqueue(
        hook_id=hook_id,
        task_id=task_id,
        callback_url=row["callback_url"],
        hmac_key_id=row["callback_hmac_key_id"] or "",
        payload=payload_body,
    )


async def run_task_completed_consumer_loop(stop_event: asyncio.Event) -> None:
    """Boucle worker — pattern aligné mom_reclaimer / provisioning_worker."""
    _log.info("workflow.task_completed_consumer.started")
    try:
        while not stop_event.is_set():
            try:
                await process_batch()
            except Exception:
                _log.exception("workflow.task_completed_consumer.loop_error")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=_DEFAULT_INTERVAL_S
                )
                break
            except TimeoutError:
                continue
    finally:
        _log.info("workflow.task_completed_consumer.stopped")
