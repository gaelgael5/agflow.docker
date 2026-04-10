# MCP — Model Context Protocol

## Catalogue

- 29 serveurs dans le catalogue (`mcp_catalog.csv`)
- Types : `npx` (80%), `uvx` (20%), `python`, `node`, `docker`, `bunx`, `deno`
- Lazy install : premier appel installe globalement, les suivants sont immédiats
- Lock par package (thread-safe, pas deux installs simultanées)
- Config : `mcp_servers.json` (global) + `agent_mcp_access.json` (par équipe)

## MCP SSE Server (agents exposés)

Chaque agent est exposable comme tool MCP via SSE :

- **Endpoint** : `GET /mcp/{team_id}/sse` (port 8123)
- **Auth** : `Authorization: Bearer lg-<payload>.<hmac>` — token HMAC-SHA256 auto-signé
- **Validation** : HMAC check (zéro DB hit) → SHA-256 hash → lookup PostgreSQL (revoked? expired?) → team check
- **Tools exposés** : intersection agents de l'équipe ∩ agents autorisés par la key
- **Table** : `project.mcp_api_keys` (key_hash, name, preview, teams, agents, expires_at, revoked)
- **Gestion** : dashboard admin → onglet Configuration → sous-onglet Sécurité
- **Secret** : `MCP_SECRET` dans `.env` — signe tous les tokens
