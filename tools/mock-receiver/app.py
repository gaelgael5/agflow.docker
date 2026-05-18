"""Mock-receiver — simule ag.flow pour les tests E2E workflow.

Utilisé par run-test.sh pour valider que le hook task-completed est :
- POSTé sur le bon URL
- Avec les 3 headers HMAC valides
- Avec une signature HMAC SHA-256 correcte
- Idempotent sur replay (hook_id seen)

Variables d'env :
    HOOK_HMAC_KEY                 Clé partagée (default: secret_v1)
    HOOK_REPLAY_WINDOW_SECONDS    Tolérance anti-replay (default: 300)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock receiver (workflow E2E)", version="5.0.0")

SHARED_SECRET = os.environ.get("HOOK_HMAC_KEY", "secret_v1")
REPLAY_WINDOW_S = int(os.environ.get("HOOK_REPLAY_WINDOW_SECONDS", "300"))

# État en mémoire (mock — pas persistant)
SEEN_HOOK_IDS: set[str] = set()
RECEIVED_HOOKS: list[dict[str, Any]] = []


def _verify_signature(timestamp: str, hook_id: str, raw_body: bytes, header: str) -> bool:
    if not header.startswith("hmac-sha256="):
        return False
    given = header.split("=", 1)[1]
    msg = (timestamp + "\n" + hook_id + "\n").encode("utf-8") + raw_body
    expected = hmac.new(
        SHARED_SECRET.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, given)


def _verify_timestamp(ts: str) -> bool:
    try:
        sent = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = abs((datetime.now(UTC) - sent).total_seconds())
    return age <= REPLAY_WINDOW_S


@app.post("/api/v1/hooks/docker/task-completed")
async def receive_hook(request: Request) -> JSONResponse:
    raw = await request.body()
    hook_id = request.headers.get("x-agflow-hook-id", "")
    timestamp = request.headers.get("x-agflow-timestamp", "")
    signature = request.headers.get("x-agflow-signature", "")

    if not _verify_timestamp(timestamp):
        return JSONResponse({"error": "timestamp_replay"}, status_code=401)

    if not _verify_signature(timestamp, hook_id, raw, signature):
        return JSONResponse({"error": "bad_signature"}, status_code=401)

    if hook_id in SEEN_HOOK_IDS:
        return JSONResponse({"ok": True, "duplicate": True})

    SEEN_HOOK_IDS.add(hook_id)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "bad_json"}, status_code=400)

    RECEIVED_HOOKS.append({
        "hook_id": hook_id,
        "timestamp": timestamp,
        "signature": signature,
        "payload": payload,
        "received_at": datetime.now(UTC).isoformat(),
    })
    return JSONResponse({"ok": True})


@app.get("/hooks")
async def list_hooks() -> dict:
    """Expose les hooks reçus pour les assertions bash de run-test.sh."""
    return {
        "count": len(RECEIVED_HOOKS),
        "hooks": RECEIVED_HOOKS,
    }


@app.delete("/hooks")
async def clear_hooks() -> dict:
    """Reset l'état mémoire (utile entre runs E2E)."""
    SEEN_HOOK_IDS.clear()
    RECEIVED_HOOKS.clear()
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "received_count": len(RECEIVED_HOOKS)}
