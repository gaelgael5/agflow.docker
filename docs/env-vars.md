# Variables d'environnement

## Culture & Canaux

```bash
CULTURE=fr-fr                    # Culture par défaut (prompts localisés)
DEFAULT_CHANNEL=discord          # Canal par défaut (discord | email)
```

## Discord

```bash
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_COMMANDS=...
DISCORD_CHANNEL_REVIEW=...
```

## Email (si DEFAULT_CHANNEL=email)

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
IMAP_HOST=imap.gmail.com
```

## LLM

```bash
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

## Base de données

```bash
DATABASE_URI=postgresql://langgraph:...@langgraph-postgres:5432/langgraph
REDIS_URI=redis://:...@langgraph-redis:6379/0
```

## HITL Console

```bash
HITL_JWT_SECRET=...           # Secret JWT (fallback: MCP_SECRET)
HITL_ADMIN_EMAIL=admin@...    # Email admin initial (seed)
HITL_ADMIN_PASSWORD=...       # Password admin initial (seed)
HITL_PUBLIC_URL=https://...   # URL publique HITL
GOOGLE_CLIENT_SECRET=...      # Secret Google OAuth (si google_oauth.enabled)
```

## Langfuse Observabilité

```bash
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=http://langfuse-web:3000
LANGFUSE_ENCRYPTION_KEY=...   # openssl rand -hex 32
LANGFUSE_SALT=...
LANGFUSE_NEXTAUTH_SECRET=...
```

## Dashboard Admin

```bash
WEB_ADMIN_USERNAME=...
WEB_ADMIN_PASSWORD=...
GIT_USER_EMAIL=...
GIT_USER_NAME=...
```

## Fichiers de configuration (non-secrets)

| Fichier | Emplacement | Contenu |
|---|---|---|
| `teams.json` | `config/` | Liste équipes + channel_mapping |
| `llm_providers.json` | `config/` | 17 providers + throttling |
| `mcp_servers.json` | `config/` | Serveurs MCP (global) |
| `langgraph.json` | `config/` | Config LangGraph |
| `hitl.json` | `config/` | Auth HITL + Google OAuth |
| `cultures.json` | `Shared/` | Référentiel cultures (31 locales) |
| `agents_registry.json` | `config/Team1/` | 13 agents + orchestrator |
| `agent_mcp_access.json` | `config/Team1/` | MCP par agent |
| `Workflow.json` | `config/Team1/` | Phases, transitions, livrables |
| `*.md` | `config/Team1/` | Prompts des agents |
| `*.md` | `Shared/Prompts/fr-fr/` | Prompts système localisés |
