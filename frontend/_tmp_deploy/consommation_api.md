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
bash(./docs/ctr/docker-api/public-agents/ListAgents.sh)
```

Retourne la liste des agents avec leur slug, nom, dockerfile, rôle.

## Étape 3 : Créer une session

```bash
bash(./docs/ctr/docker-api/untagged/CreateSession.sh '{"name": "ma-session", "duration_seconds": 3600}')
```

Retourne un `session_id` (UUID) à utiliser pour la suite.

## Étape 4 : Instancier un agent dans la session

```bash
bash(./docs/ctr/docker-api/untagged/CreateAgents.sh <session_id> '{"agent_id": "agent-helper"}')
```

Retourne un `instance_id` qui identifie cette instance d'agent dans la session.

## Étape 5 : Envoyer un message

```bash
bash(./docs/ctr/docker-api/untagged/PostMessage.sh <session_id> <instance_id> '{"kind": "instruction", "payload": {"text": "Liste les dockerfiles"}}')
```

## Étape 6 : Récupérer les réponses

### Par polling

```bash
bash(./docs/ctr/docker-api/untagged/GetSessionMessages.sh <session_id>)
```

### Par WebSocket (streaming temps réel)

```javascript
const ws = new WebSocket(`wss://${HOST}/api/v1/sessions/${sessionId}/stream`);
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log(msg.kind, msg.payload);
};
```

## Étape 7 : Fermer la session

```bash
bash(./docs/ctr/docker-api/untagged/CloseSession.sh <session_id>)
```

## Points de vigilance
- Les sessions expirent automatiquement après le `duration_seconds` configuré
- Le rate limiting est appliqué par API key (vérifier les headers `X-RateLimit-*`)
- Chaque message transite par le bus interne pour traçabilité
- Les secrets de l'agent sont résolus côté serveur — jamais exposés dans l'API publique
- Le scope de l'API key doit couvrir les actions demandées (sinon 403)

## Critère de succès
Le développeur envoie une instruction via l'API et reçoit la réponse de l'agent, soit par polling soit par WebSocket.
