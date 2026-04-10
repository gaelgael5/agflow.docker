# Architecture — Stack & Infrastructure

## Hôte
- Proxmox LXC 110 (privileged, 8 vCPU, 8GB RAM)
- OS : Ubuntu 24
- Container runtime : Docker + Docker Compose
- Données persistantes : `/opt/langgraph-data/{postgres,redis}/`

## Stack Docker

| Service | Image | Port | Rôle |
|---|---|---|---|
| `langgraph-postgres` | pgvector/pgvector:pg16 | 5432 (local) | BDD principale + pgvector (RAG) |
| `langgraph-redis` | redis:7-alpine | 6379 (local) | Cache + pub/sub |
| `langgraph-api` | Custom (Dockerfile) | **8123** | API FastAPI — gateway + agents |
| `discord-bot` | Custom (Dockerfile.discord) | — | Bot Discord — interface utilisateur |
| `langgraph-admin` | Custom (Dockerfile.admin) | **8080** | Dashboard web administration |
| `hitl-console` | Custom (Dockerfile.hitl) | **8090** | Console HITL — validation humaine web |
| `langfuse-web` | langfuse/langfuse:3 | **3000** | Observabilité LLM — UI Langfuse |
| `langfuse-worker` | langfuse/langfuse-worker:3 | — | Worker async Langfuse |
| `langfuse-clickhouse` | clickhouse/clickhouse-server | — | Stockage traces Langfuse |
| `langfuse-minio` | cgr.dev/chainguard/minio | — | S3 blob storage Langfuse |

## Scripts d'installation

| Script | Rôle |
|---|---|
| `00-create-lxc.sh` | Création LXC Proxmox + installation complète |
| `00-prepare-existing-lxc4Docker.sh` | Prépare un LXC existant pour Docker |
| `01-install-docker.sh` | Docker Engine + Compose + Caddy reverse proxy |
| `02-install-langgraph.sh` | Infra + code agents + configs équipe (paramètre branche) |
| `03-install-rag.sh` | Couche RAG (pgvector + Voyage AI) |
| `start.sh / stop.sh / restart.sh / build.sh / update.sh` | Gestion des containers + mise à jour |

## Observabilité

### EventBus interne (`agents/shared/event_bus.py`)
- Bus pub/sub singleton avec ring buffer (2000 events)
- 12 types d'events : agent_start/complete/error, llm_call_start/end, tool_call, pipeline_step_start/end, human_gate_requested/responded, agent_dispatch, phase_transition
- Handlers : Webhooks (HMAC-SHA256), Dashboard (via `/events`)

### Langfuse (port 3000)
- Self-hosted v3 (4 containers : Web + Worker + ClickHouse + MinIO)
- Intégration LangChain via `CallbackHandler` (singleton dans `langfuse_setup.py`)
- BDD dédiée `langfuse` dans PostgreSQL (séparée de `langgraph`)
- Env vars : `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`
