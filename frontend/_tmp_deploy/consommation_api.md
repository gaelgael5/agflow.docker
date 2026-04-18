# Mission : Consommer l'API publique agflow

## Déclencheur
Un développeur veut intégrer agflow dans son application — piloter des agents par programme.

## Objectif
Guider l'intégration de l'API v1 : authentification, sessions, instanciation d'agents, échange de messages et streaming.

## Prérequis
- Un agent configuré et fonctionnel (testé via le chat intégré)
- Une API key créée (page API Keys, scopes adaptés)

## Étape 1 : Créer une API key

1. Page **API Keys** > Nouvelle clé
2. Choisir les **scopes** nécessaires :
   - `agents:read` : lister et inspecter les agents
   - `agents:run` : lancer un agent (générer + exécuter)
   - `sessions:read` : lire les sessions et messages
   - `sessions:write` : créer des sessions, envoyer des messages
   - `*` : accès complet
3. La clé complète (préfixe `agflow_...`) n'est visible qu'à la création — la copier immédiatement
4. Toutes les requêtes API utilisent le header : `Authorization: Bearer agflow_...`

## Étape 2 : Lister les agents disponibles

```bash
curl -s \
  -H "Authorization: Bearer ${API_KEY}" \
  "${BASE_URL}/api/v1/agents"
```

Retourne la liste des agents avec leur slug, nom, dockerfile, rôle.

## Étape 3 : Créer une session

```bash
curl -s -X POST \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"name": "ma-session", "duration_seconds": 3600}' \
  "${BASE_URL}/api/v1/sessions"
```

Retourne un `session_id` (UUID) à utiliser pour la suite.

## Étape 4 : Instancier un agent dans la session

```bash
curl -s -X POST \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent-helper", "mission": "Aide-moi à configurer un agent"}' \
  "${BASE_URL}/api/v1/sessions/${SESSION_ID}/agents"
```

Retourne un `instance_id` qui identifie cette instance d'agent dans la session.

## Étape 5 : Envoyer un message

```bash
curl -s -X POST \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"kind": "instruction", "payload": {"text": "Liste les dockerfiles disponibles"}}' \
  "${BASE_URL}/api/v1/sessions/${SESSION_ID}/agents/${INSTANCE_ID}/message"
```

## Étape 6 : Récupérer les réponses

### Par polling
```bash
curl -s \
  -H "Authorization: Bearer ${API_KEY}" \
  "${BASE_URL}/api/v1/sessions/${SESSION_ID}/messages"
```

### Par WebSocket (streaming temps réel)
```javascript
const ws = new WebSocket(`wss://${HOST}/api/v1/sessions/${sessionId}/stream`);
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log(msg.kind, msg.payload);
};
```

Les événements poussés : messages OUT de tous les agents de la session.

## Étape 7 : Fermer la session

```bash
curl -s -X DELETE \
  -H "Authorization: Bearer ${API_KEY}" \
  "${BASE_URL}/api/v1/sessions/${SESSION_ID}"
```

## Points de vigilance
- Les sessions expirent automatiquement après le `duration_seconds` configuré
- Le rate limiting est appliqué par API key (vérifier les headers `X-RateLimit-*`)
- Chaque message transite par le bus interne pour traçabilité
- Les secrets de l'agent sont résolus côté serveur — jamais exposés dans l'API publique
- Le scope de l'API key doit couvrir les actions demandées (sinon 403)

## Intégration Python (exemple)
```python
import requests

BASE = "https://docker-agflow.yoops.org"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# Créer session
session = requests.post(f"{BASE}/api/v1/sessions",
    json={"name": "test", "duration_seconds": 600},
    headers=HEADERS).json()

# Instancier agent
instance = requests.post(
    f"{BASE}/api/v1/sessions/{session['id']}/agents",
    json={"agent_id": "agent-helper"},
    headers=HEADERS).json()

# Envoyer message
requests.post(
    f"{BASE}/api/v1/sessions/{session['id']}/agents/{instance['id']}/message",
    json={"kind": "instruction", "payload": {"text": "Liste les agents"}},
    headers=HEADERS)

# Lire réponses
messages = requests.get(
    f"{BASE}/api/v1/sessions/{session['id']}/messages",
    headers=HEADERS).json()
```

## Critère de succès
Le développeur envoie une instruction via l'API et reçoit la réponse de l'agent, soit par polling soit par WebSocket.
