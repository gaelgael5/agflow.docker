# Agents — Registry & Configuration

Définis dans `config/Team1/agents_registry.json`. Pas de fichiers Python individuels — tout passe par `BaseAgent` + registry.

## Champs du registry

```json
{
  "agents": {
    "orchestrator": {
      "name": "Orchestrateur",
      "llm": "claude-sonnet",
      "temperature": 0.2,
      "max_tokens": 4096,
      "prompt": "orchestrator.md",
      "type": "orchestrator"
    },
    "lead_dev": {
      "name": "Lead Dev",
      "llm": "claude-sonnet",
      "temperature": 0.3,
      "max_tokens": 32768,
      "prompt": "lead_dev.md",
      "type": "single",
      "use_tools": true,
      "requires_approval": false
    }
  }
}
```

## Hiérarchie de routing

L'Orchestrateur reçoit le contexte enrichi par le workflow engine :
- `suggested_agents_to_dispatch` : recommandation du workflow
- `phase_complete` / `can_transition` : état de la phase
- Il suit les recommandations du workflow sauf cas particulier

Le Lead Dev est le seul à dispatcher vers les devs (frontend, backend, mobile).

## Résolution des fichiers — team_resolver.py

Source unique de vérité. Logique :
1. Trouve le dossier de config racine (celui qui contient `teams.json`) parmi : `config/`, `/app/config/`
2. Lit `teams.json` pour trouver le `directory` d'une équipe
3. Résout les chemins : `config/<directory>/<fichier>`
4. Fallback global si le fichier n'existe pas dans le dossier de l'équipe

### Modules qui l'utilisent

| Module | Fichiers cherchés via team_resolver |
|---|---|
| `agent_loader.py` | `agents_registry.json`, `agent_mcp_access.json` |
| `base_agent.py` | Prompts `.md` |
| `workflow_engine.py` | `Workflow.json` |
| `orchestrator.py` | `agents_registry.json`, `orchestrator.md` |
| `llm_provider.py` | `llm_providers.json` |
| `rate_limiter.py` | `llm_providers.json` (throttling) |
| `mcp_client.py` | `mcp_servers.json`, `agent_mcp_access.json` |

## Multi-équipes (teams.json)

```json
{
  "teams": [
    { "id": "team1", "name": "Team 1", "directory": "Team1", "discord_channels": [] }
  ],
  "channel_mapping": {}
}
```

Chaque équipe a son propre registry, workflow, prompts, MCP access, et channel Discord.

## Human Gate & Ask Human

- **Human Gate** : `requires_approval: true` → validation via `channels.approve()` (Discord ou Email)
- **Ask Human** : tool `ask_human(question, context)` → via `channels.ask()`
- Timeout 30 min avec 4 rappels (2, 4, 8, 16 min)
- Gateway timeout 35 min (couvre l'attente humaine)
