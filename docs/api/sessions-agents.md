# API publique V1 — Sessions & Agents

## 1. Introduction

L'API Sessions V1 permet d'ouvrir des **bacs à sable isolés** (sessions), d'y instancier des agents IA (instances), et d'échanger des instructions avec eux via un bus de messages orienté message (MOM) Redis Streams. Chaque session est délimitée dans le temps (TTL configurable), et sa fermeture détruit en cascade toutes les instances actives. Les échanges en temps réel sont exposés via WebSocket ; l'historique complet est accessible par GET. Le bus sous-jacent est Redis Streams avec consumer groups (`dispatcher`, `ws_push`, `router`).

---

## 2. Authentification

Tous les endpoints (sauf les connexions WebSocket, authentifiées par le contexte de connexion réseau) exigent un header HTTP :

```
Authorization: Bearer <token>
```

Le token est une clé API au format `agfd_` suivi de 48 caractères hexadécimaux, par exemple :

```
agfd_a1b2c3d4e5f6ffffffff0102030405060708090a0b0c0d
```

### Générer une clé via l'interface admin

```bash
# Via l'interface web admin (M0 Secrets)
# Ou via l'endpoint admin dédié :
curl -X POST http://192.168.10.158/api/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "mon-client",
    "scopes": ["sessions:write", "agents:run"],
    "rate_limit": 120
  }'
```

La réponse contient le `full_key` affiché **une seule fois**. Conservez-le immédiatement.

---

## 3. Règles de scoping

| Situation | Comportement |
|---|---|
| Token normal | Ne voit et ne modifie que les ressources créées avec sa propre clé (`api_key_id = <caller>`) |
| Token admin (`scopes` contient `"*"`) | Voit et modifie toutes les ressources, tous propriétaires confondus |

Un token normal qui tente d'accéder à une session appartenant à un autre `api_key_id` reçoit `404 Not Found` (pas `403`) — l'existence de la ressource n'est pas divulguée.

Voir la section [7. Exemples de scoping](#7-exemples-de-scoping) pour des exemples concrets.

---

## 4. Codes d'erreur communs

| Code HTTP | `error.code` | Cause |
|---|---|---|
| `400` | `bad_request` | Corps invalide, contrainte violée (ex. `agent_id` introuvable dans le catalogue) |
| `401` | `missing_token` | Header `Authorization` absent |
| `401` | `invalid_format` | Token ne respecte pas le format `agfd_…` |
| `401` | `invalid_checksum` | HMAC du token incorrect |
| `401` | `expired` | Clé API expirée |
| `401` | `revoked_or_unknown` | Clé révoquée ou inconnue en base |
| `403` | `missing_scope` | La clé n'a pas le scope requis |
| `404` | — | Ressource introuvable ou appartenant à un autre propriétaire |
| `409` | — | Conflit d'état (ex. session déjà fermée/expirée) |
| `422` | — | Validation Pydantic (champ manquant, valeur hors bornes) |
| `429` | `rate_limited` | Limite de requêtes dépassée (par fenêtre d'une minute) ; header `Retry-After` inclus |

Format de corps d'erreur :

```json
{
  "error": {
    "code": "missing_scope",
    "message": "This key lacks the 'agents:run' scope"
  }
}
```

---

## 5. Endpoints

---

### 5.1 POST /api/v1/sessions — Créer une session

Ouvre un nouveau bac à sable isolé avec une durée de vie limitée. La session passe automatiquement à l'état `expired` à l'échéance si elle n'est pas fermée explicitement.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

Aucun.

#### Corps de la requête

| Champ | Type | Obligatoire | Défaut | Contraintes |
|---|---|---|---|---|
| `name` | `string \| null` | Non | `null` | Texte libre, max 255 caractères |
| `duration_seconds` | `integer` | Non | `3600` | min `60`, max `86400` |

```json
{
  "name": "my-run",
  "duration_seconds": 1800
}
```

#### Réponse 201

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "api_key_id": "11111111-2222-3333-4444-555555555555",
  "name": "my-run",
  "status": "active",
  "created_at": "2026-04-16T09:00:00Z",
  "expires_at": "2026-04-16T09:30:00Z",
  "closed_at": null
}
```

Statuts possibles : `active`, `closed`, `expired`.

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `422` | `duration_seconds` hors bornes ou type invalide |
| `429` | Rate limit dépassé |

#### Exemple

```bash
API=http://192.168.10.158
TOKEN=agfd_a1b2c3d4e5f6ffffffff0102030405060708090a0b0c0d

curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-run","duration_seconds":1800}'
```

---

### 5.2 GET /api/v1/sessions/{session_id} — Lire l'état d'une session

Retourne l'état courant d'une session. Un token non-admin ne peut lire que ses propres sessions.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Réponse 200

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "api_key_id": "11111111-2222-3333-4444-555555555555",
  "name": "my-run",
  "status": "active",
  "created_at": "2026-04-16T09:00:00Z",
  "expires_at": "2026-04-16T09:30:00Z",
  "closed_at": null
}
```

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou appartenant à un autre propriétaire |
| `429` | Rate limit dépassé |

#### Exemple

```bash
SESSION_ID=550e8400-e29b-41d4-a716-446655440000

curl -s $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN"
```

---

### 5.3 PATCH /api/v1/sessions/{session_id}/extend — Prolonger le TTL

Ajoute une durée supplémentaire à la date d'expiration d'une session **active**. Idempotent si appliqué plusieurs fois.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Corps de la requête

| Champ | Type | Obligatoire | Contraintes |
|---|---|---|---|
| `duration_seconds` | `integer` | Oui | min `60`, max `86400` |

```json
{
  "duration_seconds": 900
}
```

#### Réponse 200

La session mise à jour avec la nouvelle `expires_at` :

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "api_key_id": "11111111-2222-3333-4444-555555555555",
  "name": "my-run",
  "status": "active",
  "created_at": "2026-04-16T09:00:00Z",
  "expires_at": "2026-04-16T09:45:00Z",
  "closed_at": null
}
```

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable, appartenant à un autre propriétaire, ou déjà fermée/expirée |
| `422` | `duration_seconds` hors bornes ou absent |
| `429` | Rate limit dépassé |

#### Exemple

```bash
curl -s -X PATCH $API/api/v1/sessions/$SESSION_ID/extend \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds":900}'
```

---

### 5.4 DELETE /api/v1/sessions/{session_id} — Fermer une session

Ferme une session active et détruit en cascade toutes ses instances d'agents. La session passe à l'état `closed`. Opération irréversible.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Réponse 204

Corps vide.

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable, appartenant à un autre propriétaire, ou déjà fermée/expirée |
| `429` | Rate limit dépassé |

#### Exemple

```bash
curl -s -X DELETE $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nHTTP %{http_code}\n"
```

---

### 5.5 POST /api/v1/sessions/{session_id}/agents — Instancier des agents

Crée N instances d'un agent référencé dans le catalogue. L'`agent_id` est le **slug** de l'agent (ex. `claude-code`, `aider`). La session doit être à l'état `active`.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session active |

#### Corps de la requête

| Champ | Type | Obligatoire | Défaut | Contraintes |
|---|---|---|---|---|
| `agent_id` | `string` | Oui | — | Slug kebab-case (`[a-z0-9][a-z0-9-]{0,63}`) |
| `count` | `integer` | Non | `1` | min `1`, max `50` |
| `labels` | `object` | Non | `{}` | Métadonnées libres clé/valeur |
| `mission` | `string \| null` | Non | `null` | Instruction de départ envoyée à chaque instance |

```json
{
  "agent_id": "claude-code",
  "count": 2,
  "labels": {"env": "staging", "task": "refactor"},
  "mission": "Analyse le dépôt et propose un plan de refactoring."
}
```

#### Réponse 201

```json
{
  "instance_ids": [
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "ffffffff-1111-2222-3333-444444444444"
  ]
}
```

#### Erreurs

| Code | Cause |
|---|---|
| `400` | `agent_id` introuvable dans le catalogue |
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou pas à l'état `active` |
| `422` | `agent_id` format invalide, `count` hors bornes |
| `429` | Rate limit dépassé |

#### Exemple

```bash
curl -s -X POST $API/api/v1/sessions/$SESSION_ID/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "claude-code",
    "count": 2,
    "labels": {"env": "staging"},
    "mission": "Analyse le dépôt et propose un plan de refactoring."
  }'
```

---

### 5.6 GET /api/v1/sessions/{session_id}/agents — Lister les instances actives

Retourne toutes les instances d'agents rattachées à la session, qu'elles soient actives ou détruites.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Réponse 200

```json
[
  {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "agent_id": "claude-code",
    "labels": {"env": "staging"},
    "mission": "Analyse le dépôt et propose un plan de refactoring.",
    "status": "running",
    "created_at": "2026-04-16T09:01:00Z"
  },
  {
    "id": "ffffffff-1111-2222-3333-444444444444",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "agent_id": "claude-code",
    "labels": {"env": "staging"},
    "mission": "Analyse le dépôt et propose un plan de refactoring.",
    "status": "running",
    "created_at": "2026-04-16T09:01:00Z"
  }
]
```

Statuts possibles : `pending`, `running`, `stopped`, `destroyed`.

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou appartenant à un autre propriétaire |
| `429` | Rate limit dépassé |

#### Exemple

```bash
curl -s $API/api/v1/sessions/$SESSION_ID/agents \
  -H "Authorization: Bearer $TOKEN"
```

---

### 5.7 DELETE /api/v1/sessions/{session_id}/agents/{instance_id} — Détruire une instance

Détruit une instance d'agent identifiée par son UUID. La session doit appartenir au caller (ou le caller doit être admin).

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |
| `instance_id` | UUID | Identifiant de l'instance à détruire |

#### Réponse 204

Corps vide.

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable, ou instance introuvable dans la session |
| `429` | Rate limit dépassé |

#### Exemple

```bash
INSTANCE_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee

curl -s -X DELETE $API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nHTTP %{http_code}\n"
```

---

### 5.8 POST /api/v1/sessions/{session_id}/agents/{instance_id}/message — Envoyer une instruction

Publie un message entrant (`direction: in`) sur le bus MOM à destination d'une instance spécifique. La session doit être `active` et l'instance doit exister et ne pas être détruite.

Le message est persisté en base (`agent_messages`) et publié sur le stream Redis du consumer group `dispatcher`.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |
| `instance_id` | UUID | Identifiant de l'instance cible |

#### Corps de la requête

| Champ | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `kind` | `string` | Non | `"instruction"` | Type de message : `instruction`, `cancel`, `event`, `result`, `error` |
| `payload` | `object` | Oui | — | Corps libre du message (JSON quelconque) |
| `route_to` | `string \| null` | Non | `null` | Cible de routage MOM, format `agent:<id>`, `team:<id>`, `pool:<id>` ou `session:<id>` |

```json
{
  "kind": "instruction",
  "payload": {
    "text": "Liste les 5 fichiers les plus importants du projet."
  }
}
```

#### Réponse 201

```json
{
  "msg_id": "cccccccc-dddd-eeee-ffff-000000000001"
}
```

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou instance inexistante/détruite |
| `409` | Session pas à l'état `active` (fermée ou expirée) |
| `422` | `payload` absent ou `kind` invalide |
| `429` | Rate limit dépassé |

#### Exemple

```bash
INSTANCE_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee

curl -s -X POST $API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "instruction",
    "payload": {"text": "Liste les 5 fichiers les plus importants du projet."}
  }'
```

---

### 5.9 GET /api/v1/sessions/{session_id}/agents/{instance_id}/messages — Historique d'une instance

Retourne les messages échangés avec une instance spécifique, triés par `created_at` décroissant.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |
| `instance_id` | UUID | Identifiant de l'instance |

#### Paramètres de requête (query string)

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `kind` | `string` | — | Filtre par type : `instruction`, `cancel`, `event`, `result`, `error` |
| `direction` | `string` | — | Filtre par direction : `in` (envoyés) ou `out` (reçus de l'agent) |
| `limit` | `integer` | `100` | Nombre maximum de messages retournés |

#### Réponse 200

```json
[
  {
    "msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
    "parent_msg_id": null,
    "direction": "in",
    "kind": "instruction",
    "payload": {"text": "Liste les 5 fichiers les plus importants du projet."},
    "source": "api_key:11111111-2222-3333-4444-555555555555",
    "created_at": "2026-04-16T09:02:00Z",
    "route": null
  },
  {
    "msg_id": "dddddddd-eeee-ffff-0000-111111111111",
    "parent_msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
    "direction": "out",
    "kind": "result",
    "payload": {"text": "Voici les 5 fichiers : main.py, config.py, ..."},
    "source": "agent:claude-code",
    "created_at": "2026-04-16T09:02:15Z",
    "route": null
  }
]
```

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou appartenant à un autre propriétaire |
| `429` | Rate limit dépassé |

#### Exemple

```bash
# Tous les messages d'une instance
curl -s "$API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID/messages" \
  -H "Authorization: Bearer $TOKEN"

# Uniquement les réponses sortantes (limit 20)
curl -s "$API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID/messages?direction=out&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 5.10 WebSocket /api/v1/sessions/{session_id}/agents/{instance_id}/stream — Flux temps réel d'une instance

Connexion WebSocket qui pousse en temps réel les messages sortants (`direction: out`) d'une instance spécifique. Basé sur le consumer group Redis Streams `ws_push`.

**Authentification** : la connexion WebSocket ne porte pas de header `Authorization`. L'accès est contrôlé par la sécurité réseau (connexion depuis un host autorisé).

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |
| `instance_id` | UUID | Identifiant de l'instance à surveiller |

#### Messages reçus (JSON)

Chaque événement poussé par le serveur a la structure suivante :

```json
{
  "msg_id": "dddddddd-eeee-ffff-0000-111111111111",
  "parent_msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
  "direction": "out",
  "kind": "result",
  "payload": {"text": "Voici les 5 fichiers : main.py, config.py, ..."},
  "source": "agent:claude-code",
  "created_at": "2026-04-16T09:02:15Z",
  "route": null
}
```

Le serveur ne pousse aucun message de keepalive. Fermez la connexion côté client quand vous n'en avez plus besoin.

#### Exemple

```bash
# Avec websocat (https://github.com/vi/websocat)
websocat "ws://192.168.10.158/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID/stream"

# Avec wscat (npm install -g wscat)
wscat -c "ws://192.168.10.158/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_ID/stream"
```

---

### 5.11 GET /api/v1/sessions/{session_id}/messages — Historique consolidé de la session

Retourne l'ensemble des messages de tous les agents de la session, triés par `created_at` décroissant. Inclut le champ `instance_id` pour identifier l'origine de chaque message.

**Scopes requis** : aucun (clé API valide suffit)

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Paramètres de requête (query string)

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `kind` | `string` | — | Filtre par type : `instruction`, `cancel`, `event`, `result`, `error` |
| `direction` | `string` | — | Filtre par direction : `in` ou `out` |
| `limit` | `integer` | `200` | Nombre maximum de messages retournés |

#### Réponse 200

```json
[
  {
    "msg_id": "dddddddd-eeee-ffff-0000-111111111111",
    "parent_msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
    "instance_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "direction": "out",
    "kind": "result",
    "payload": {"text": "Voici les 5 fichiers : main.py, config.py, ..."},
    "source": "agent:claude-code",
    "created_at": "2026-04-16T09:02:15Z",
    "route": null
  },
  {
    "msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
    "parent_msg_id": null,
    "instance_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "direction": "in",
    "kind": "instruction",
    "payload": {"text": "Liste les 5 fichiers les plus importants du projet."},
    "source": "api_key:11111111-2222-3333-4444-555555555555",
    "created_at": "2026-04-16T09:02:00Z",
    "route": null
  }
]
```

#### Erreurs

| Code | Cause |
|---|---|
| `401` | Token manquant, invalide ou expiré |
| `404` | Session introuvable ou appartenant à un autre propriétaire |
| `429` | Rate limit dépassé |

#### Exemple

```bash
# Toute l'activité de la session (max 200)
curl -s "$API/api/v1/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $TOKEN"

# Seulement les réponses des agents
curl -s "$API/api/v1/sessions/$SESSION_ID/messages?direction=out&limit=50" \
  -H "Authorization: Bearer $TOKEN"
```

---

### 5.12 WebSocket /api/v1/sessions/{session_id}/stream — Flux temps réel de toute la session

Connexion WebSocket qui pousse en temps réel **tous** les messages sortants (`direction: out`) de **tous les agents** de la session. Identique à 5.10 mais agrégé au niveau session. Utilise un polling en base (intervalle 200 ms) plutôt qu'un consumer group Redis.

**Authentification** : contrôlée par la sécurité réseau (pas de header Bearer sur WS).

#### Paramètres de chemin

| Paramètre | Type | Description |
|---|---|---|
| `session_id` | UUID | Identifiant de la session |

#### Messages reçus (JSON)

```json
{
  "msg_id": "dddddddd-eeee-ffff-0000-111111111111",
  "parent_msg_id": "cccccccc-dddd-eeee-ffff-000000000001",
  "instance_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "direction": "out",
  "kind": "result",
  "payload": {"text": "Voici les 5 fichiers : main.py, config.py, ..."},
  "source": "agent:claude-code",
  "created_at": "2026-04-16T09:02:15Z",
  "route": null
}
```

Le champ `instance_id` permet d'identifier quel agent a produit chaque événement.

#### Exemple

```bash
# Avec websocat
websocat "ws://192.168.10.158/api/v1/sessions/$SESSION_ID/stream"

# Avec wscat
wscat -c "ws://192.168.10.158/api/v1/sessions/$SESSION_ID/stream"
```

---

## 6. Scénario bout en bout

Script bash complet : ouvrir une session, instancier 2 agents, envoyer un message à chacun, lire les réponses, puis fermer la session.

```bash
#!/usr/bin/env bash
set -euo pipefail

API=http://192.168.10.158
TOKEN=agfd_a1b2c3d4e5f6ffffffff0102030405060708090a0b0c0d

# ── 1. Ouvrir une session (30 minutes) ───────────────────────────────────────
SESSION=$(curl -sf -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"demo-e2e","duration_seconds":1800}')

SESSION_ID=$(echo $SESSION | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Session ouverte : $SESSION_ID"

# ── 2. Vérifier l'état de la session ─────────────────────────────────────────
curl -sf $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# ── 3. Instancier 2 agents claude-code ───────────────────────────────────────
AGENTS=$(curl -sf -X POST $API/api/v1/sessions/$SESSION_ID/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "claude-code",
    "count": 2,
    "labels": {"role": "analyst"},
    "mission": "Tu es un expert en analyse de code Python."
  }')

INSTANCE_1=$(echo $AGENTS | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_ids'][0])")
INSTANCE_2=$(echo $AGENTS | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_ids'][1])")
echo "Instance 1 : $INSTANCE_1"
echo "Instance 2 : $INSTANCE_2"

# ── 4. Lister les instances actives ──────────────────────────────────────────
curl -sf $API/api/v1/sessions/$SESSION_ID/agents \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# ── 5. Envoyer une instruction à l'instance 1 ────────────────────────────────
MSG1=$(curl -sf -X POST $API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_1/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "instruction",
    "payload": {"text": "Quels sont les anti-patterns les plus fréquents en Python async ?"}
  }')
echo "Message envoyé à instance 1 : $(echo $MSG1 | python3 -c "import sys,json; print(json.load(sys.stdin)['msg_id'])")"

# ── 6. Envoyer une instruction à l'instance 2 ────────────────────────────────
MSG2=$(curl -sf -X POST $API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_2/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "instruction",
    "payload": {"text": "Comment optimiser les requêtes asyncpg avec des pool connections ?"}
  }')
echo "Message envoyé à instance 2 : $(echo $MSG2 | python3 -c "import sys,json; print(json.load(sys.stdin)['msg_id'])")"

# ── 7. Attendre quelques secondes que les agents répondent ───────────────────
sleep 5

# ── 8. Lire l'historique de l'instance 1 ─────────────────────────────────────
echo "=== Historique instance 1 ==="
curl -sf "$API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_1/messages?direction=out" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# ── 9. Lire l'historique consolidé de la session ─────────────────────────────
echo "=== Historique consolidé ==="
curl -sf "$API/api/v1/sessions/$SESSION_ID/messages?limit=50" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# ── 10. Prolonger la session de 15 minutes supplémentaires ───────────────────
curl -sf -X PATCH $API/api/v1/sessions/$SESSION_ID/extend \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds":900}' | python3 -m json.tool

# ── 11. Détruire l'instance 2 manuellement ───────────────────────────────────
curl -sf -X DELETE $API/api/v1/sessions/$SESSION_ID/agents/$INSTANCE_2 \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nDELETE instance 2 → HTTP %{http_code}\n"

# ── 12. Fermer la session (détruit l'instance 1 en cascade) ──────────────────
curl -sf -X DELETE $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nDELETE session → HTTP %{http_code}\n"

echo "Scénario terminé."
```

---

## 7. Exemples de scoping

### Token propriétaire — accès autorisé

```bash
# TOKEN_OWNER a créé la session SESSION_ID → 200 OK
curl -s $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN_OWNER"
# Réponse : {"id": "550e8400-...", "status": "active", ...}
```

### Token étranger — accès refusé (404, pas 403)

```bash
# TOKEN_OTHER appartient à un autre api_key_id → 404 Not Found
# L'existence de la session n'est pas divulguée.
curl -s $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN_OTHER"
# Réponse : {"detail": "session not found"}
```

### Token admin — accès à toutes les sessions

```bash
# TOKEN_ADMIN a le scope "*" → voit toutes les sessions, tous propriétaires
curl -s $API/api/v1/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN_ADMIN"
# Réponse : {"id": "550e8400-...", "api_key_id": "...", "status": "active", ...}
```

La même règle s'applique à tous les endpoints : `GET`, `PATCH /extend`, `DELETE`, et l'accès aux agents et messages d'une session.
