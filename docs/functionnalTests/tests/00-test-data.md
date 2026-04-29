# 00 — Données de référence des tests fonctionnels

> **📋 Cartouche — Document de référence (pas de tests exécutables)**
>
> **Rôle** : centralise les variables d'env, fixtures plateforme, payloads,
> résultats attendus et conventions d'assertion partagés par tous les tests
> applicatifs (01-09) et opérateur (A01-A03).
>
> **Sections** :
> 1. Variables d'environnement (`BASE_URL`, `API_KEY`, `ADMIN_JWT`, `WS_URL`, `PROJECT_UUID`)
> 2. Données de référence — état attendu de la plateforme (secrets, agents, MCP, projet, API keys)
> 3. Fixtures par scénario (3.1 à 3.9 — un bloc par cas applicatif)
> 4. Fixtures pour les scénarios opérateur (A01-A03)
> 5. Conventions d'assertion (variables capturées, codes HTTP, `jq -e`)
> 6. Nettoyage global
>
> **Implémentation runtime** : `00-test-data.sh` (helpers sourceables + CLI `check`/`jwt`/`cleanup`)

Ce document décrit **toutes les données nécessaires** pour exécuter les 12 scénarios de
tests fonctionnels (`01-09` applicatifs + `A01-A03` opérateur). Il est lu **avant** les
tests : chaque test référence par nom les fixtures, payloads et résultats attendus
définis ici.

> ⚠️ Les tests ne s'exécutent pas tant que `BASE_URL` et `API_KEY` ne pointent pas vers
> un environnement déployé. Voir `README.md` pour la procédure de bootstrap.

---

## 1. Variables d'environnement

| Variable | Type | Origine | Utilisée par |
|----------|------|---------|--------------|
| `BASE_URL` | `https://...` (sans slash final) | URL publique de l'environnement de test | tous |
| `API_KEY` | string brute (`agflow_...`) | Émise par l'opérateur après A01 | 01-09 |
| `ADMIN_EMAIL` | email | Bootstrap admin local OU SSO | A01-A03, génération `API_KEY` |
| `ADMIN_PASSWORD` | string | id. | id. |
| `ADMIN_JWT` | JWT | `POST /api/admin/auth/login` | A01-A03 |
| `WS_URL` | `wss://...` (sans slash final, dérivé de `BASE_URL`) | calculé : `https://x` → `wss://x` | 05, 09 (streaming) |
| `PROJECT_UUID` | UUID | Sortie de A03 | 04 |

Export type avant exécution :

```bash
export BASE_URL="https://docker-agflow-staging.yoops.org"   # à remplacer
export WS_URL="${BASE_URL/https:/wss:}"
export API_KEY="agflow_xxxxxxxxxxxxxxxxxxxxxxx"             # fourni par opérateur
```

Pour les scénarios A01-A03 (opérateur), récupérer un JWT admin :

```bash
ADMIN_JWT=$(curl -s -X POST "$BASE_URL/api/admin/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
  | jq -r '.access_token')
export ADMIN_JWT
```

Outils requis sur la machine d'exécution : `curl`, `jq`, `wscat`
(`npm install -g wscat`).

---

## 2. Données de référence — état attendu de la plateforme

Ces fixtures doivent exister **avant** d'exécuter les tests applicatifs. Si l'env est
vierge, exécuter d'abord A01 (puis A02 et A03 selon les scénarios visés).

### 2.1 Secrets plateforme

| Nom de variable | Description | Requis pour |
|----------------|-------------|-------------|
| `ANTHROPIC_API_KEY` | Clé valide Anthropic (sk-ant-...) | tous les scénarios qui instancient un agent (01-09) |

> Validation côté plateforme : `POST /api/admin/secrets/{id}/test` doit renvoyer `{"ok": true}`.

### 2.2 Catalogue agents

Au minimum **un agent** instanciable doit être présent. Convention pour les tests :

| Slug | Rôle attendu | Image build OK | Utilisé par |
|------|--------------|----------------|-------------|
| `claude-code` | Assistant générique (réponse texte simple) | oui | 01-03, 05-07, 09 |

Vérification :

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/agents" \
  | jq '.[] | {id, slug, has_errors, image_status}'
# Attendu : claude-code présent, has_errors=false, image_status="up_to_date"
```

> Si plusieurs agents sont disponibles, les tests acceptent un override via la variable
> `AGENT_SLUG` (par défaut `claude-code`).

### 2.3 Projet de test (cas 04)

| Champ | Valeur |
|-------|--------|
| `display_name` | `Tests fonctionnels` |
| `PROJECT_UUID` | UUID retourné à la création — exporté pour cas 04 |

> Les projets sont identifiés par UUID (pas de slug). A03 émet `PROJECT_UUID`
> (à exporter avant cas 04). La gestion des ressources initiales (fichiers
> spec) n'est pas exposée par une API "fichiers projet" en V1 — voir notes du
> A03 et du test 04.

Setup via A03.

### 2.4 MCP installé (cas 04)

| Champ | Valeur |
|-------|--------|
| Discovery service URL | `https://mcp.yoops.org/api/v1` |
| Package recherché | `filesystem` (recipe `stdio`) |
| Bindé à l'agent | `claude-code` |

Setup via A02.

### 2.5 Dockerfile pour tâche one-shot (cas 08)

| Champ | Valeur |
|-------|--------|
| Slug dockerfile | `claude-code` (réutilise le même que les agents) |
| Status build | `up_to_date` |
| `Dockerfile.json` présent | oui (requis par l'endpoint) |

> Pas de setup spécifique — réutilise le bootstrap A01.

### 2.6 API keys de test à émettre

Trois clés sont nécessaires selon les scénarios :

| Variable | Scopes | Rate limit | Utilisée par |
|----------|--------|------------|--------------|
| `API_KEY` | `agents:read`, `agents:run`, `roles:read`, `containers.chat:read`, `containers.chat:write` | 120/min | 01-09 (sauf A*) |
| `API_KEY_STRANGER` | mêmes scopes que `API_KEY` | 120/min | non utilisé V1 (réservé itération erreurs) |
| `API_KEY_LOW_SCOPE` | `agents:read` uniquement | 120/min | 07 (vérification scopes) |

Remarque : les routes `POST/GET/DELETE /api/v1/sessions*` n'imposent **pas** de scope
spécifique (elles vérifient simplement qu'une clé est présente et le scoping
propriétaire). Les scopes ci-dessus couvrent les endpoints discovery/launched.

---

## 3. Fixtures par scénario

### 3.1 Cas 01 — single-agent-request

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-01-single` |
| `session.duration_seconds` | `600` |
| `agent.mission` | `"Réponds en une phrase à la question de l'utilisateur."` |
| `agent.count` | `1` |
| `message.kind` | `instruction` |
| `message.payload` | `{"text": "Quel est le code ISO du Japon ?"}` |
| Polling | 10 itérations max, 2s entre chaque, jusqu'à un message `direction=out`, `kind=result` |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| Création session | 201 | `.id` UUID, `.status="active"` |
| Création agent | 201 | `.instance_ids \| length == 1` |
| POST message | 201 | `.msg_id` UUID |
| Polling messages | 200 | au moins 1 message `direction=out` apparaît avant 60s |
| DELETE session | 204 | corps vide |
| GET après close | 200 | `.status="closed"` |

### 3.2 Cas 02 — parallel-agents

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-02-parallel` |
| `session.duration_seconds` | `600` |
| `agent.count` | `2` (un seul appel POST `/agents` avec `count=2`) |
| `agent.mission` | `"Tu es un agent de test parallèle."` |
| Message A | `{"text": "Liste 3 villes françaises."}` (envoyé sur `instance_ids[0]`) |
| Message B | `{"text": "Liste 3 villes japonaises."}` (envoyé sur `instance_ids[1]`) |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| POST `/agents count=2` | 201 | `.instance_ids \| length == 2` |
| POST messages A et B | 201 chacun | `.msg_id` distinct |
| GET `/sessions/{sid}/messages` | 200 | au moins 2 messages `direction=out` (un par instance) en ≤ 60s |
| Filtrage `instance_id` | 200 | chaque résultat porte `instance_id` correspondant à son instance |

### 3.3 Cas 03 — inter-agent-communication

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-03-router` |
| `session.duration_seconds` | `600` |
| `agent.count` | `2` (`IID_A`, `IID_B`) |
| Message routé | `{"kind":"instruction","payload":{"text":"Demande à B"},"route_to":"agent:$IID_B"}` |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| POST message routé sur A | 201 | `.msg_id` UUID |
| Après 3s — GET messages IN de B | 200 | au moins 1 message `direction=in`, `parent_msg_id` non nul |
| GET messages OUT de A | 200 | message avec `route.target == "agent:$IID_B"` |

> Le worker MOM Router doit tourner sur l'env de test (cf. supervision Phase 1).

### 3.4 Cas 04 — project-resources-and-mcp

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-04-project` |
| `session.project_id` | `$PROJECT_UUID` (UUID émis par A03) |
| `session.duration_seconds` | `1200` |
| `agent.mission` | `"Lis specs/feature-x.md et propose un résumé."` |
| Message | `{"text": "Documente la fonctionnalité X en lisant les specs"}` |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| Création session avec `project_id` | 201 | `.project_id == "tests-fixture-project"` |
| GET session | 200 | `.project_id == "tests-fixture-project"` |
| Création agent | 201 | `.instance_ids` non vide |
| Polling messages OUT | 200 | au moins 1 message `kind=result` ou `kind=event` mentionnant la lecture du fichier |

> **Limitation V1 connue** (cf. `COVERAGE.md` écart 1) : la lecture/écriture des
> ressources projet via API publique HTTP n'est pas exposée. Le test vérifie
> l'**héritage du scope projet** dans la session ; la vérification effective de la
> lecture se fait via inspection workspace (cas 09) ou logs.

### 3.5 Cas 05 — streaming-live-results

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-05-stream` |
| WebSocket | `${WS_URL}/api/v1/sessions/{sid}/agents/{iid}/stream` |
| Header WS | `Authorization: Bearer $API_KEY` (passé en query string si nécessaire) |
| Message | `{"text": "Compte de 1 à 5 lentement"}` |
| Timeout WS | 60s |

Résultat attendu :

| Étape | Assertion |
|-------|-----------|
| Connexion WS | accepte (HTTP 101) |
| Après POST message | au moins 1 frame JSON reçu en ≤ 60s |
| Format de frame | `{msg_id, parent_msg_id, instance_id, direction, kind, payload, source, created_at, route}` |
| Filtrage | tous les frames ont `direction == "out"` |

> Le WS d'instance ne nécessite pas d'authentification dans l'implémentation actuelle
> (vérifier sur l'env). Si l'auth est ajoutée, passer la clé via query `?api_key=...`.

### 3.6 Cas 06 — long-running-session-extension

| Donnée | Valeur |
|--------|--------|
| `session.duration_seconds` initial | `120` (2 min — assez court pour observer l'extension) |
| Extension `additional_seconds` | `1800` |
| Délai d'attente avant extension | `10s` |
| Délai d'attente après extension | `30s` (puis vérifier que la session n'est pas expirée) |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| Création session | 201 | `.expires_at` ≈ `created_at + 120s` |
| GET session | 200 | `.status="active"` |
| PATCH `/extend` | 200 | `.expires_at` repoussé d'environ +1800s |
| Après 30s — GET session | 200 | `.status="active"` (toujours active malgré dépassement de la durée initiale) |

### 3.7 Cas 07 — discovery-before-instantiation

| Donnée | Valeur |
|--------|--------|
| Aucune session ni agent à créer | — |
| Filtre exemple | `agent.slug == "claude-code"` |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| `GET /api/v1/scopes` | 200 | tableau non vide, contient au moins `agents:read`, `agents:run` |
| `GET /api/v1/roles` | 200 | tableau non vide, chaque entrée a `id`, `display_name` |
| `GET /api/v1/agents` | 200 | `claude-code` présent |
| `GET /api/v1/agents/{id}` | 200 | `.role_id`, `.mcp_bindings`, `.skill_bindings`, `.timeout_seconds`, `.has_errors`, `.image_status` exposés |
| `GET /api/v1/agents/{id}` avec `API_KEY_LOW_SCOPE` | 200 | identique (a le scope `agents:read`) |

> **Limitation V1 connue** (cf. `COVERAGE.md` écart 2) : `AgentDetail` n'expose pas
> de tableau `profiles`. Le test ne vérifie donc pas la sélection de profil de mission.

### 3.8 Cas 08 — one-shot-task-no-session

| Donnée | Valeur |
|--------|--------|
| `dockerfile_id` | `claude-code` (slug) |
| `instruction` | `"Affiche le mot OK et termine"` |
| `timeout_seconds` | `60` |
| `model` | `""` (utilise le défaut) |

Résultat attendu :

| Étape | Assertion |
|-------|-----------|
| `POST /dockerfiles/{slug}/task` | content-type `application/x-ndjson`, premier événement `{"type":"started","task_id":"...","dockerfile_id":"claude-code"}` |
| Stream NDJSON | au moins un événement intermédiaire (stdout / event), terminé par `{"type":"done","status":"...","exit_code":0}` |
| `GET /api/v1/launched?dockerfile_id=claude-code` | 200 | tableau contient le `task_id` reçu, avec `status="finished"` (ou `"error"` si timeout) |

### 3.9 Cas 09 — post-mortem-logs-and-files

> Prérequis : exécuter d'abord cas 01 (ou cas 05) en notant `SID` et `IID`. Ne pas
> nettoyer la session avant de lancer ce test (ou la fermer puis lire dans la même
> session de test).

| Donnée | Valeur |
|--------|--------|
| `SID`, `IID` | repris d'un test précédent |
| Path workspace | `""` (racine) puis sous-dossier `"workspace"` |

Résultat attendu :

| Étape | HTTP | Assertion |
|-------|------|-----------|
| `GET .../messages?limit=100` | 200 | tableau non vide |
| `GET .../logs?limit=200` | 200 | content-type `text/plain`, lignes au format `[ts] [kind] text` |
| `GET .../files?path=` | 200 | objet `{type:"dir"\|"missing", entries:[...]}` |
| `GET .../files?path=` (sur fichier) | 200 | content-type `application/octet-stream` |

---

## 4. Fixtures pour les scénarios opérateur (A01-A03)

### 4.1 A01 — platform-bootstrap

| Étape | Donnée |
|-------|--------|
| Login admin | `ADMIN_EMAIL`, `ADMIN_PASSWORD` |
| Création secret | `name=ANTHROPIC_API_KEY`, `value=$ANTHROPIC_API_KEY_VALUE` (env var hors repo) |
| Création dockerfile | `slug=claude-code`, `image_name=claude-code` |
| Upload fichiers dockerfile | `Dockerfile`, `entrypoint.sh`, `Dockerfile.json` (depuis fixtures locales — voir `tests/fixtures/dockerfile-claude-code/`) |
| Build dockerfile | timeout poll 10 minutes |
| Création rôle | `id=test-assistant`, `display_name=Test Assistant` |
| Création agent | `slug=claude-code`, `role_id=test-assistant`, `dockerfile_id={id}` |
| Création API key | `name=tests-functional`, `scopes=["agents:read","agents:run","roles:read","containers.chat:read","containers.chat:write"]`, `rate_limit=120`, `expires_in="3m"` |

Résultat attendu : `full_key` retourné une seule fois. Stocker dans `API_KEY` env var.

### 4.2 A02 — mcp-integration

| Étape | Donnée |
|-------|--------|
| Création discovery service | `name=yoops-mcp`, `url=https://mcp.yoops.org/api/v1`, `auth=none` |
| Test connectivity | doit retourner `{"ok": true}` |
| Recherche package | `query=filesystem` |
| Installation MCP | `package_id={id retourné}`, `recipe=stdio`, `params={"root":"/tmp"}` |
| Binding à l'agent | `agent_id={id de claude-code}`, `mcp_id={id installé}` |
| Preview config | doit montrer le bloc MCP résolu |

Résultat attendu : binding visible via `GET /api/admin/agents/{id}/mcp`.

### 4.3 A03 — project-setup

| Étape | Donnée |
|-------|--------|
| Création projet | `display_name=Tests fonctionnels` |
| Création groupe (optionnel) | `name=specs` |
| Upload ressources | `path=specs/feature-x.md`, `content=<markdown ≥ 100 octets>` |
| Vérification finale | `GET /api/admin/projects/tests-fixture-project` doit montrer le projet et ses ressources |

---

## 5. Conventions d'assertion

### Variables capturées au fil du test

Convention de nommage pour réutilisation entre étapes d'un même test :

| Variable | Source | Cycle de vie |
|----------|--------|--------------|
| `SID` | `.id` de `POST /sessions` | survit au test, nettoyée à la fin |
| `IID` | `.instance_ids[0]` de `POST /sessions/{sid}/agents` | survit au test |
| `IID_A`, `IID_B` | id. avec `count=2` ou 2 appels successifs | id. |
| `MID` | `.msg_id` de `POST /messages` | utilisé pour corrélation/parent |
| `TID` | `.task_id` de l'événement `started` du stream NDJSON | cas 08 |

### Codes HTTP attendus

| Action | Code |
|--------|------|
| `POST /sessions`, `POST /agents`, `POST /message` | **201 Created** |
| `GET ...` | **200 OK** |
| `PATCH /extend` | **200 OK** |
| `DELETE /sessions/{id}`, `DELETE .../agents/{iid}`, `DELETE /launched/{tid}` | **204 No Content** |
| Session inconnue ou non possédée | **404 Not Found** |
| Agent slug inexistant au catalogue | **400 Bad Request**, `detail` contient `not found in catalog` |
| Session non active (closed/expired) | **404** sur `/agents`, **409** sur `/message` |
| Scope manquant | **403 Forbidden** |
| Rate limit dépassé | **429 Too Many Requests**, header `Retry-After` |

### Outil de vérification

Chaque test renvoie son verdict via `jq -e` (exit code 1 si l'assertion échoue) afin
qu'il soit chaînable dans un script CI :

```bash
echo "$RESPONSE" | jq -e '.id and .status == "active"' >/dev/null \
  || { echo "FAIL: session creation"; exit 1; }
```

---

## 6. Nettoyage global

Après exécution complète du parcours :

```bash
# Lister toutes les sessions ouvertes par le test
curl -s -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/sessions" 2>/dev/null \
  | jq -r '.[] | select(.name | startswith("test-")) | .id' \
  | while read SID; do
      curl -s -X DELETE -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/sessions/$SID"
    done
```

> Note : `GET /api/v1/sessions` n'existe pas en V1 (pas d'endpoint de listing public).
> Le nettoyage repose donc sur les `SID` notés au cours du test ou sur un appel admin.

Pour les ressources créées par A01-A03, prévoir un nettoyage manuel ciblé (suppression
de la clé API de test, du projet, du binding MCP). Détaillé dans chaque fichier `A0X-*.md`.
