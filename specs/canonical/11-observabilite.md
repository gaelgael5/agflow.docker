# 11 — Observabilité

L'observabilité de agflow.docker se décline en deux familles :

1. **Logs centralisés** dans Loki + Grafana, collectés par Grafana Alloy sur toutes les machines actives.
2. **Supervision temps réel** intégrée au panneau admin (M7), basée sur PostgreSQL `pg_notify` et WebSocket.

## Stack de logs

### Architecture

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  agflow.docker backend   │    │  Machine cible           │
│  (structlog JSON)        │    │  (containers conteneurs)│
└──────────┬───────────────┘    └─────────┬────────────────┘
           │                              │
           │ stdout JSON                  │ Docker socket
           │                              │ + journald
           │                              │ + fichiers .log
           ▼                              ▼
       ┌───────────────────────────────────────────┐
       │  Grafana Alloy (sur chaque machine)        │
       │  - lit Docker socket                        │
       │  - lit journald                             │
       │  - parse JSON                                │
       │  - injecte labels (machine, container, …)   │
       └───────────────────┬───────────────────────┘
                           │
                           │ Loki push API
                           ▼
       ┌───────────────────────────────────────────┐
       │  Loki + Grafana (LXC agflow-logs)          │
       │  - rétention 7 jours                        │
       │  - exposé sur log.yoops.org                 │
       │  - auth SSO Keycloak realm yoops            │
       └───────────────────────────────────────────┘
```

### LXC agglow-logs

Un LXC dédié `agflow-logs` héberge la stack centralisée :
- **Loki** : index + storage des logs.
- **Grafana** : UI de consultation, dashboards.
- Exposé sur `https://log.yoops.org` via Cloudflare Tunnel.
- Authentification via SSO Keycloak (client `grafana` du realm `yoops`) — seuls les admins agflow.docker ont accès.
- Rétention 7 jours (configurable côté `infra/logs-stack/`).

### Grafana Alloy

Déployé sur **toutes les machines actives** (backend de la plateforme + machines cibles déployant des project_runtimes). Configuration dans `infra/alloy-agent/`.

Sources collectées :
- **Docker socket** : logs de tous les containers, avec labels automatiques (`container_name`, `image`, `agflow.instance_id` si applicable).
- **journald** : logs systemd de la machine.
- **Fichiers** : si besoin pour des composants qui n'écrivent ni dans Docker ni dans journald.

Labels injectés :
- `machine` : nom de la machine d'origine.
- `environment` : champ `environment` de la machine (`dev`, `prod`, …).
- `agflow_runtime_id`, `agflow_group_runtime_id`, `agflow_instance_id` : extraits des labels Docker quand présents.
- `service` : nom du service (extrait de `docker-compose` ou auto-détecté).
- `level` : `info` / `warn` / `error` extrait du JSON structlog quand applicable.

### Format des logs backend

Tous les logs backend agflow.docker sont **JSON structlog**, jamais `print()`. Forme typique :

```json
{
  "event": "deployment.push.started",
  "level": "info",
  "timestamp": "2026-05-25T14:32:10.123Z",
  "logger": "agflow.workers.deployment_executor",
  "deployment_id": "uuid",
  "project_id": "uuid",
  "machine_name": "lxc-201"
}
```

Conventions :
- `event` : nom canonique en `domain.action.state` (`deployment.push.started`, `agent.message.received`, `auth.login.failure`).
- `level` : `debug` (developpement), `info` (nominal), `warning` (incident mineur), `error` (incident grave).
- Champs contextuels : préfixés par leur domaine quand possible (`deployment_*`, `agent_*`, `user_*`).
- Pas de valeurs sensibles (jamais de mot de passe, token, clé API en clair dans les logs).

### Recherches typiques dans Loki

```logql
# Toutes les erreurs sur la dernière heure
{environment="prod", level="error"}

# Logs d'une session spécifique
{agflow_runtime_id="abc-123"} | json

# Tous les hooks sortants en échec
{logger="agflow.workers.hook_dispatcher_worker", level="warning"} 
  | json | event="hook.delivery.failed"
```

## Supervision temps réel (M7)

### Vue d'ensemble (`SupervisionPage`)

Le tableau de bord principal affiche en temps réel :

1. **4 KPI cards** :
   - Sessions par statut (`active` / `closed` / `expired`).
   - Agents par statut (`idle` / `busy` / `error` / `destroyed_total`).
   - Containers en cours d'exécution.
   - Statistiques MOM : `pending` / `claimed` / `failed`.

2. **Liste filtrable** des instances d'agents en cours, avec statut, agent_id, session_id, dernière activité, container.

3. **Drawer détail** : ouvre le détail d'une instance, ses messages récents, son container Docker, les compteurs de delivery.

4. **Indicateur de flux temps réel** : composant `SupervisionStreamIndicator` qui affiche l'état du WebSocket (déconnecté / en cours / actif).

### Endpoints REST

| Endpoint | Rôle |
|---|---|
| `GET /api/admin/supervision/overview` | `SupervisionOverview` (4 KPI) |
| `GET /api/admin/supervision/instances?status=…&limit=` | Liste paginée des instances |
| `GET /api/admin/supervision/instances/{id}` | Détail complet d'une instance (avec messages, MOM counts, container) |

### Stream WebSocket

Endpoint : `GET /api/admin/supervision/stream` (auth JWT en query param `?token=…` car les WebSocket n'autorisent pas les headers custom dans la spec WS).

Le backend :
1. Souscrit au canal PostgreSQL `pg_notify('supervision_events', payload_json)`.
2. Pour chaque notification, pousse un message WebSocket au client.

Types d'événements publiés :
- `instance.created` : nouvelle instance d'agent créée.
- `instance.status_changed` : transition de statut.
- `instance.destroyed` : instance terminée.
- `session.created` / `session.closed` / `session.expired`.
- `container.started` / `container.exited`.
- `task.created` / `task.completed`.
- `message.published` : nouveau message en attente de delivery.

### Hook React

Le hook `useSupervisionStream` côté frontend :
- Établit la connexion WebSocket avec le JWT.
- Gère la reconnexion automatique (backoff exponentiel `1s → 2s → 4s → … → 30s` max).
- Pour chaque event reçu, invalide **chirurgicalement** les queries TanStack Query concernées :
  - `instance.status_changed` → invalide `['supervision-instance', instance_id]` et `['supervision-instances']`.
  - `session.closed` → invalide `['supervision-overview']` et `['supervision-instances']`.
  - Etc.

### Publication d'événements depuis le code

Les services métier publient les événements via une fonction utilitaire :

```python
from agflow.services.supervision_events import publish

await publish(
    event="instance.status_changed",
    instance_id=instance.id,
    old_status=old,
    new_status=new,
)
```

qui appelle `pg_notify('supervision_events', json.dumps(payload))`.

Cinq publishers sont implémentés :
- `agents_instances_service.create` / `update` / `destroy`.
- `sessions_service.create` / `close`.
- (Voir code pour la liste à jour.)

### Indicateur de connexion

`SupervisionStreamIndicator` affiche en haut de la page un badge :
- Gris « Connexion en cours… » au boot.
- Vert « Temps-réel actif » après réception du premier event.
- Orange « Reconnexion… » pendant le backoff.
- Rouge « Hors-ligne » si toutes les tentatives échouent.

## Métriques d'exploitation

### Métriques métier

Pas de Prometheus / cardinalité poussée à ce stade. Les métriques sont **calculées en SQL à la volée** par `supervision_overview` et les endpoints associés. Cela évite la complexité d'une stack métriques séparée pour un volume de données modeste.

Si le besoin émerge, l'archi prévoit une exposition `/metrics` Prometheus côté backend ; à activer dans une évolution future.

### Métriques techniques de PostgreSQL

Le LXC PostgreSQL expose ses propres métriques via `pg_stat_statements`, `pg_stat_activity`, etc. consultables via `pgweb` (interface admin SQL) à `http://192.168.10.154:8081/` dans l'environnement de test.

### Métriques WAL et basebackups (PITR)

Endpoints dédiés (cf. module 10) :
- `GET /api/admin/pitr/wal-status` : `archiving_enabled`, `last_archived_at`, `archive_lag_seconds`, `wal_disk_used_bytes`, `wal_disk_free_bytes`.
- `GET /api/admin/pitr/restore-window` : fenêtre de restauration disponible.

## Tests et qualité

### Tests fonctionnels structurés

Le dossier `docs/functionnalTests/tests/` contient une douzaine de scénarios end-to-end documentés en markdown, exécutables par un agent IA ou un opérateur humain.

Chaque scénario a un **cartouche** standardisé :
- Pré-requis (clés API, environnement).
- Pas à pas avec commandes curl ou actions UI.
- Assertions attendues.

Catégories :
- `01-single-agent-request.md` à `09-post-mortem-logs-and-files.md` : scénarios élémentaires (agent unique, agents parallèles, communication inter-agents, ressources MCP, streaming, sessions longues, découverte avant instanciation, tâches one-shot, post-mortem).
- `A01-A03-…` : scénarios avancés.
- Suite « SaaS runtimes phase 1 » avec 10 cas.

Le helper `docs/functionnalTests/tests/00-test-data.sh` (sourceable) prépare des fixtures.

### Test d'intégration automatisé

`./scripts/run-test.sh` est le runner de tests d'intégration **autorité** :
1. Pousse les scripts sur l'hôte Proxmox.
2. Crée un LXC fresh (range 400-499 dédié aux tests auto Claude).
3. Clone la branche en cours.
4. Déploie agflow.docker complet.
5. Lance les assertions (smoke API : 6 checks, smoke UI Playwright, suite pytest backend complète).
6. Optionnellement (`CLEANUP=1`) détruit le LXC.

Le détail des assertions vit dans `docs/test.md`.

### Test humain

Les LXC 300-399 sont réservés aux tests manuels par un opérateur humain. Provisionnés via `remote-deploy.ps1 <id>` à la demande. Persistants entre sessions.

### Conventions de tests Python

- pytest + pytest-asyncio.
- Fixture `client` : `httpx.AsyncClient` qui pointe sur l'app FastAPI.
- Fixture `fresh_db` : reset complet du schéma puis ré-application de `001_init.sql` (utilisée par les tests d'intégration DB).
- Tests purs (sans DB) : `tests/services/test_<service>_*.py` quand applicable.
- Tests d'intégration : `tests/services/test_<service>_integration.py` ou regroupés par module.
- Seuils de couverture par zone définis dans `docs/tests-python.md`.

### Conventions de tests Frontend

- Vitest + React Testing Library.
- `describe` / `it`, pas `test`.
- Tests par composant + tests d'intégration page pour les chemins critiques.

## Alertes (opérationnelles)

agflow.docker n'embarque pas de système d'alertes propre. La détection d'anomalies se fait via les outils standards de la stack :

- **Loki alertmanager** (configurable côté `infra/logs-stack/`) : alertes sur les logs (ex: « plus de 10 hooks failed en 5 min »).
- **Health checks Cloudflare Tunnel** : si la route applicative tombe, Cloudflare bascule (selon config) ou alerte l'admin.
- **Email d'admin** : configurable côté `platform_config` pour les notifications critiques manuelles (rotation de clé qui échoue, etc.).

Une intégration plus poussée (PagerDuty, OpsGenie, Slack) est hors-scope du projet de base mais peut être ajoutée comme webhook sortant signé HMAC (cf. module 07).
