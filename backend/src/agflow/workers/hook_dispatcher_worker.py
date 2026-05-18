"""Worker dispatcher des hooks sortants signés HMAC v5.

Pattern aligné sur mom_reclaimer / provisioning_worker (asyncio + stop_event).
Poll outbound_hooks WHERE status='pending' AND next_retry_at <= now(),
charge la clé HMAC déchiffrée, POST httpx avec les 3 headers requis :
  - X-Agflow-Hook-Id
  - X-Agflow-Timestamp
  - X-Agflow-Signature

Politique de réponse :
  - 2xx → mark_delivered
  - 5xx ou timeout → schedule_retry (backoff)
  - 4xx sauf 408/429 → mark_dead (non-retryable)
  - Au-delà de MAX_ATTEMPTS retries → mark_dead
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import structlog

from agflow.services import hmac_keys_service, hook_signing, outbound_hooks_service

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 2.0
_HTTP_TIMEOUT_S = 10.0

_NON_RETRYABLE_4XX = frozenset({400, 401, 403, 404, 422})  # 408/429 sont retryables


def _safe_response_excerpt(response: httpx.Response, limit: int = 200) -> str:
    """Extrait jusqu'à `limit` octets du corps de la réponse en mode tolérant.

    Évite UnicodeDecodeError si le corps n'est pas UTF-8 valide (ex: HTML mal
    encodé, binaire). Toujours retourne un string même sur corps non décodable.
    """
    try:
        content = response.content[:limit]
        return content.decode("utf-8", errors="replace")
    except Exception:
        return f"<unreadable response body, {len(response.content)} bytes>"


async def process_batch() -> None:
    hooks = await outbound_hooks_service.claim_pending(limit=10)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
        for hook in hooks:
            await _process_hook(client, hook)


async def _process_hook(client: httpx.AsyncClient, hook: dict) -> None:
    hook_id: UUID = hook["hook_id"]

    # Charge le secret HMAC (peut lever si Fernet token corrompu)
    try:
        key = await hmac_keys_service.get_by_key_id(hook["hmac_key_id"])
    except Exception as exc:
        _log.exception(
            "workflow.hook_dispatcher.hmac_key_load_failed",
            hook_id=str(hook_id),
            hmac_key_id=hook["hmac_key_id"],
        )
        await outbound_hooks_service.mark_dead(
            hook_id=hook_id,
            error_message=f"hmac key load failed: {exc!s}",
        )
        return

    if key is None:
        await outbound_hooks_service.mark_dead(
            hook_id=hook_id,
            error_message=f"hmac key '{hook['hmac_key_id']}' not found",
        )
        return

    # Sérialise le body exactement comme il sera envoyé (byte-pour-byte)
    payload = hook["payload"]
    if isinstance(payload, str):
        # asyncpg may return jsonb as str depending on version
        body = payload
    else:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = datetime.now(UTC).isoformat()
    signature_hex = hook_signing.sign(
        timestamp=timestamp,
        hook_id=str(hook_id),
        body=body,
        secret_hex=key["secret_hex"],
    )
    headers = {
        "Content-Type": "application/json",
        "X-Agflow-Hook-Id": str(hook_id),
        "X-Agflow-Timestamp": timestamp,
        "X-Agflow-Signature": f"hmac-sha256={signature_hex}",
    }

    try:
        response = await client.post(hook["callback_url"], content=body, headers=headers)
    except httpx.TimeoutException as exc:
        await outbound_hooks_service.schedule_retry(
            hook_id=hook_id, response_code=None, error_message=f"timeout: {exc}"
        )
        return
    except httpx.RequestError as exc:
        await outbound_hooks_service.schedule_retry(
            hook_id=hook_id,
            response_code=None,
            error_message=f"network error: {exc}",
        )
        return

    status_code = response.status_code
    if 200 <= status_code < 300:
        await outbound_hooks_service.mark_delivered(
            hook_id=hook_id, response_code=status_code
        )
        return
    if status_code in _NON_RETRYABLE_4XX:
        await outbound_hooks_service.mark_dead(
            hook_id=hook_id,
            error_message=f"non-retryable {status_code}: {_safe_response_excerpt(response)}",
        )
        return
    # 5xx, 408, 429 → retry
    await outbound_hooks_service.schedule_retry(
        hook_id=hook_id,
        response_code=status_code,
        error_message=f"{status_code}: {_safe_response_excerpt(response)}",
    )


async def run_hook_dispatcher_loop(stop_event: asyncio.Event) -> None:
    _log.info("workflow.hook_dispatcher.started")
    try:
        while not stop_event.is_set():
            try:
                await process_batch()
            except Exception:
                _log.exception("workflow.hook_dispatcher.loop_error")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_DEFAULT_INTERVAL_S)
                break
            except TimeoutError:
                continue
    finally:
        _log.info("workflow.hook_dispatcher.stopped")
