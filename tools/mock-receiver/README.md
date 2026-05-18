# Mock-receiver (workflow E2E)

Container FastAPI minimal qui simule le récepteur de hooks `ag.flow` côté
agflow.docker. Utilisé par `scripts/run-test.sh` pour valider bout-en-bout
l'émission HMAC du `hook_dispatcher_worker`.

## Endpoints

- `POST /api/v1/hooks/docker/task-completed` — vérifie HMAC + idempotence + stocke le hook
- `GET /hooks` — liste les hooks reçus (assertions bash)
- `DELETE /hooks` — reset état (entre runs)
- `GET /health` — healthcheck

## Variables d'env

- `HOOK_HMAC_KEY` : secret partagé avec agflow.docker (doit matcher la row `hmac_keys` créée par le test)
- `HOOK_REPLAY_WINDOW_SECONDS` : tolérance anti-replay (default 300s)

## Démarrage local (debug)

```bash
HOOK_HMAC_KEY=test_secret uv run uvicorn app:app --port 8001
```

## Démarrage via compose

Voir `docker-compose.dev.yml` service `mock-receiver`.
