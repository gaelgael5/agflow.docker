# Tests fonctionnels — workflows de communication

Ce répertoire contient les **workflows de communication** qu'une application cliente doit
suivre pour consommer les ressources d'`agflow.docker` (sessions, agents, MOM, projets,
MCP, ressources projet).

Chaque fichier décrit **un cas d'usage** sous forme de diagramme `sequenceDiagram`
mermaid, enrichi d'un contexte métier et des invariants que l'implémentation doit garantir.
Ces workflows sont **fonctionnels** : ils ne décrivent pas l'implémentation interne
(pas de `pg_notify`, pas d'`INSERT`, pas de WebSocket), uniquement le contrat vu
de l'extérieur.

## Progression pédagogique

Deux familles de scénarios :

- **01–09** : flux **applicatifs** (côté client qui consomme la plateforme).
- **A01–A03** : parcours **opérateur** (setup admin qui débloque les flux applicatifs).

### Scénarios applicatifs (client)

| # | Fichier | Ce qu'il ajoute |
|---|---------|-----------------|
| 01 | [single-agent-request.md](01-single-agent-request.md) | Cas minimum : 1 app, 1 session, 1 agent, 1 demande synchrone ack puis résultat asynchrone |
| 02 | [parallel-agents.md](02-parallel-agents.md) | 2 agents dans la même session, demandes parallèles, résultats collectés indépendamment |
| 03 | [inter-agent-communication.md](03-inter-agent-communication.md) | 2 agents qui coopèrent : l'un délègue à l'autre via le bus avant de répondre |
| 04 | [project-resources-and-mcp.md](04-project-resources-and-mcp.md) | La session appartient à un projet ; l'agent lit/écrit les ressources du projet et interroge un MCP externe |
| 05 | [streaming-live-results.md](05-streaming-live-results.md) | Remplace le polling par un canal streaming pour recevoir les événements en temps réel |
| 06 | [long-running-session-extension.md](06-long-running-session-extension.md) | Surveille l'expiration d'une session longue et la prolonge sans interrompre l'agent |
| 07 | [discovery-before-instantiation.md](07-discovery-before-instantiation.md) | Découvre le catalogue (scopes, rôles, agents, profils) avant d'instancier |
| 08 | [one-shot-task-no-session.md](08-one-shot-task-no-session.md) | Lance une tâche ponctuelle sans session via un stream unique (webhook, cron, CLI) |
| 09 | [post-mortem-logs-and-files.md](09-post-mortem-logs-and-files.md) | Reconstruit a posteriori ce qui s'est passé : messages, logs et workspace d'une session terminée |

### Scénarios opérateur (setup admin)

| # | Fichier | Ce qu'il débloque |
|---|---------|-------------------|
| A01 | [platform-bootstrap.md](A01-platform-bootstrap.md) | Bootstrap minimum (auth → secrets → dockerfile → rôle → agent → API key). Requis pour 01, 02, 03, 05, 06, 07, 09. |
| A02 | [mcp-integration.md](A02-mcp-integration.md) | Installe un MCP depuis un registre de découverte et le binde à un agent. Requis pour la partie MCP du cas 04. |
| A03 | [project-setup.md](A03-project-setup.md) | Crée un projet et y dépose les ressources initiales. Requis pour la partie projet du cas 04. |

### Couverture OpenAPI

- [COVERAGE.md](COVERAGE.md) — Audit des scénarios contre le contrat OpenAPI déployé. Liste les endpoints réellement utilisés, les écarts détectés (projet côté public, profils de mission, parent_msg_id, WebSockets hors OpenAPI) et les décisions à prendre.

## Acteurs conventionnels

Pour garder les diagrammes lisibles, on réutilise toujours les mêmes participants :

| Acteur | Rôle |
|--------|------|
| `App` | Application cliente externe qui veut consommer agflow (humain ou système tiers) |
| `Sessions` | API publique d'agflow exposée côté client (lifecycle sessions + agents + messages) |
| `Bus` | MOM bus asynchrone interne d'agflow (découplage ack/résultat, routage inter-agents) |
| `AgentA` / `AgentB` | Instances d'agents rattachées à une session |
| `Project` | Ressources partagées d'un projet (fichiers livrables, état partagé) |
| `MCP` | Registre MCP externe (`mcp.yoops.org`) interrogé via un outil MCP installé sur l'agent |

## Conventions mermaid

- Flèche pleine `->>` : appel synchrone (bloque jusqu'à réponse)
- Flèche en pointillés `-->>` : réponse / acquittement / notification
- Notes `Note over X` : invariant ou état observable à ce moment
- Boucle `loop` : polling ou retry
- Blocs `par` / `and` : branches parallèles
- Blocs `alt` / `else` : réservés aux itérations futures (les happy paths ne branchent pas)

## Hypothèses communes

- L'application a déjà une **API key** valide (scope `sessions:write`) — la création de la clé est hors workflow.
- Les **agents utilisés sont déjà installés** dans le catalogue et leur image Docker a déjà été buildée.
- Les **timeouts idle** (session 2 min, agent configurable) sont actifs mais n'interviennent pas dans le happy path.
- L'ordre des messages entre deux acteurs est garanti par le bus (pas de réordonnancement implicite).

## Ce qui n'est pas ici

- **Chemins d'erreur** (session expirée, agent timeout, message perdu) : itération future.
- **Scénarios de tests exécutables** (curl, pytest) : voir `docs/test-plans/`.
- **Détails d'implémentation** (schéma DB, workers de supervision) : voir `specs/home.md` et `docs/patterns/`.
- **Scénarios multi-projets** ou **partage de session entre utilisateurs** : itération future (ACL `session_users`).
