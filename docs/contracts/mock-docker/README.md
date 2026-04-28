# Mock Docker service — implémentation de référence v5

> Implémentation FastAPI minimale du contrat
> [`docker-orchestration-flow.md` v5](../docker-orchestration-flow.md). Sert de
> mock pour que ag.flow (workflow) écrive et teste son client sans dépendre
> d'une vraie implémentation Docker.

## Ce que le mock fait

- Implémente les **8 endpoints v5** (`GET /projects`, `GET /projects/{id}`,
  `POST /projects/{id}/runtimes`, `GET /project-runtimes/{id}/resources`,
  `POST /sessions`, `POST /sessions/{sid}/agents`,
  `POST /sessions/{sid}/agents/{aid}/work`, `DELETE /sessions/{sid}`).
- Stocke l'état en mémoire (perdu au restart).
- Provisionne 2 projets templates en dur :
  - `11111111-1111-4111-a111-111111111111` — "Plateforme location vélos" (wiki + repo)
  - `22222222-2222-4222-a222-222222222222` — "Documentation interne" (wiki seul)
- Simule l'asynchronicité avec `asyncio.sleep` (durées configurables).
- **Émet le hook task-completed signé HMAC** vers `callback_url` de la session
  (pas de retry — best effort, c'est un mock).
- Vérifie l'auth via `Authorization: Bearer <api_key>`.
- Vérifie que `_agflow_action_execution_id` et `_agflow_correlation_id` dans
  `instruction` sont des UUID v4 (renvoie 400 sinon).

## Ce que le mock ne fait PAS

- Aucun container Docker réel ne tourne.
- Aucun retry sur le hook (1 tentative seulement).
- Aucune persistance — restart = état perdu.
- Pas de validation sémantique du contenu de `instruction.prompt`.
- Pas de gestion de timeout des sessions.

## Lancer le mock

### Prérequis

- Python 3.12
- `pip install -r requirements.txt` ou `uv pip install -r requirements.txt`

### Démarrage

```bash
# Variables d'env (toutes optionnelles)
export MOCK_API_KEYS="agfd_test_key_12345,agfd_alt_key_67890"
export MOCK_HMAC_KEYS="v1:secret_v1,v2:secret_v2"
export MOCK_RUNTIME_PROVISION_DELAY_S="3"   # durée simulée provisioning runtime
export MOCK_WORK_DURATION_S="2"             # durée simulée d'un work agent

# Lance sur :8080
uvicorn app:app --port 8080 --reload
```

> **Note Windows** : si tu lances sur Windows (mingw bash, PowerShell), exporte
> aussi `PYTHONUTF8=1` et `PYTHONIOENCODING=utf-8` sinon les `print()` du
> receiver crashent en cp1252.

### Avec uv (recommandé, pas d'install pip)

```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  uv run --with fastapi --with httpx --with pydantic --with 'uvicorn[standard]' \
  uvicorn app:app --port 8080
```

Health check : `curl http://localhost:8080/health` → `{"status":"ok","version":"5.0.0","type":"mock"}`.

## Workflow type d'utilisation côté ag.flow

```bash
export DOCKER_BASE="http://localhost:8080"
export DOCKER_API_KEY="agfd_test_key_12345"
H_AUTH=(-H "Authorization: Bearer $DOCKER_API_KEY")

# 1. catalogue
curl -s "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/projects" | jq .

# 2. créer runtime
RT=$(curl -s -X POST "$DOCKER_BASE/api/admin/projects/11111111-1111-4111-a111-111111111111/runtimes" \
  "${H_AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"velos prod","metadata":{}}')
RT_ID=$(echo "$RT" | jq -r '.docker_project_runtime_id')
echo "runtime $RT_ID provisioning..."

# 3. polling jusqu'à ready
while true; do
  S=$(curl -s "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/project-runtimes/$RT_ID/resources" | jq -r '.status')
  echo "status: $S"
  [[ "$S" == "ready" ]] && break
  sleep 1
done

# 4. ouvrir une session avec callback
SS=$(curl -s -X POST "$DOCKER_BASE/api/admin/sessions" \
  "${H_AUTH[@]}" -H "Content-Type: application/json" \
  -d "{
    \"project_runtime_id\": \"$RT_ID\",
    \"callback_url\": \"http://localhost:9090\",
    \"callback_hmac_key_id\": \"v1\",
    \"duration_seconds\": 3600
  }")
SS_ID=$(echo "$SS" | jq -r '.session_id')

# 5. instancier agent
AG=$(curl -s -X POST "$DOCKER_BASE/api/admin/sessions/$SS_ID/agents" \
  "${H_AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"slug":"architect-v1"}')
AG_ID=$(echo "$AG" | jq -r '.agent_uuid')
echo "$AG" | jq '.mcp_bindings_injected'

# 6. soumettre work
WORK=$(curl -s -X POST "$DOCKER_BASE/api/admin/sessions/$SS_ID/agents/$AG_ID/work" \
  "${H_AUTH[@]}" -H "Content-Type: application/json" \
  -d '{
    "instruction": {
      "_agflow_action_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "_agflow_correlation_id": "11ee8400-e29b-41d4-a716-446655440008",
      "title": "Définir l'architecture",
      "prompt": "Tu es un architecte logiciel..."
    }
  }')
TASK_ID=$(echo "$WORK" | jq -r '.task_id')

# 7. ag.flow va recevoir le hook task-completed sur http://localhost:9090
#    après MOCK_WORK_DURATION_S secondes
sleep 5

# 8. fermer session
curl -s -X DELETE "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/sessions/$SS_ID"
```

## Tester l'envoi du hook localement

ag.flow a besoin d'un endpoint pour recevoir le hook. Pour le développement,
utiliser un simple receiver Python :

```python
# hook_receiver.py
from fastapi import FastAPI, Request
import hmac, hashlib

app = FastAPI()
SECRET = "secret_v1"  # doit matcher MOCK_HMAC_KEYS côté mock

@app.post("/api/v1/hooks/docker/task-completed")
async def hook(request: Request):
    raw = await request.body()
    sig_header = request.headers.get("x-agflow-signature", "")
    ts = request.headers.get("x-agflow-timestamp", "")
    hook_id = request.headers.get("x-agflow-hook-id", "")
    msg = (ts + "\n" + hook_id + "\n").encode() + raw
    expected = "hmac-sha256=" + hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(sig_header, expected)
    print(f"hook {hook_id} valid={valid}")
    print(raw.decode())
    return {"ok": True} if valid else ({"error": "bad_sig"}, 401)
```

```bash
uvicorn hook_receiver:app --port 9090
```

## Mode automatique

Lancer le smoke test sans rien écrire à la main :

```bash
bash ../smoke-test.sh
```

(cf. `docs/contracts/smoke-test.sh` qui exécute la séquence complète et
vérifie chaque réponse contre le contrat).
