"""Hook receiver minimal — simule le côté ag.flow.

Vérifie la signature HMAC, log le hook reçu, idempotence sur hook_id.

Utilisation :
    HOOK_HMAC_KEY=secret_v1 uvicorn hook_receiver:app --port 9090

Variables d'env :
    HOOK_HMAC_KEY                 Clé partagée avec le mock (default: secret_v1)
    HOOK_REPLAY_WINDOW_SECONDS    Tolérance anti-replay (default: 300)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Hook receiver (mock ag.flow)", version="5.0.0")

SHARED_SECRET = os.environ.get("HOOK_HMAC_KEY", "secret_v1")
REPLAY_WINDOW_S = int(os.environ.get("HOOK_REPLAY_WINDOW_SECONDS", "300"))

# Idempotence : hook_ids déjà traités
SEEN_HOOK_IDS: set[str] = set()


def _verify_signature(timestamp: str, hook_id: str, raw_body: bytes, header: str) -> bool:
    if not header.startswith("hmac-sha256="):
        return False
    given = header.split("=", 1)[1]
    msg = (timestamp + "\n" + hook_id + "\n").encode("utf-8") + raw_body
    expected = hmac.new(SHARED_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


def _verify_timestamp(ts: str) -> bool:
    try:
        sent = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = abs((datetime.now(timezone.utc) - sent).total_seconds())
    return age <= REPLAY_WINDOW_S


@app.post("/api/v1/hooks/docker/task-completed")
async def receive_hook(request: Request) -> JSONResponse:
    raw = await request.body()
    hook_id = request.headers.get("x-agflow-hook-id", "")
    timestamp = request.headers.get("x-agflow-timestamp", "")
    signature = request.headers.get("x-agflow-signature", "")

    print(f"\n-- hook recu hook_id={hook_id}", flush=True)
    print(f"   timestamp={timestamp}", flush=True)
    print(f"   signature={signature[:30]}...", flush=True)

    if not _verify_timestamp(timestamp):
        print("   FAIL timestamp hors fenetre", flush=True)
        return JSONResponse({"error": "timestamp_replay"}, status_code=401)

    if not _verify_signature(timestamp, hook_id, raw, signature):
        print("   FAIL signature HMAC invalide", flush=True)
        return JSONResponse({"error": "bad_signature"}, status_code=401)

    if hook_id in SEEN_HOOK_IDS:
        print("   WARN hook_id deja recu - idempotence 200", flush=True)
        return JSONResponse({"ok": True, "duplicate": True})

    SEEN_HOOK_IDS.add(hook_id)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("   FAIL body JSON invalide", flush=True)
        return JSONResponse({"error": "bad_json"}, status_code=400)

    print(f"   OK status={payload.get('status')} agent_slug={payload.get('agent_slug')}", flush=True)
    print(f"   task_id={payload.get('task_id')}", flush=True)
    print(f"   action_execution_id={payload.get('action_execution_id')}", flush=True)
    if payload.get("status") == "completed":
        print(f"   summary={(payload.get('result', {}) or {}).get('summary', '')[:100]}", flush=True)
    elif payload.get("status") == "failed":
        print(f"   error.code={(payload.get('error', {}) or {}).get('code')}", flush=True)

    return JSONResponse({"ok": True})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "type": "hook-receiver", "received": str(len(SEEN_HOOK_IDS))}
