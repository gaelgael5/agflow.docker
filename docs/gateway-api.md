# Gateway API — gateway.py v0.6.0

## Endpoints

| Endpoint | Méthode | Rôle |
|---|---|---|
| `/health` | GET | Health check |
| `/status` | GET | Liste agents + équipes |
| `/invoke` | POST | Appel agent (direct ou orchestré) |
| `/reset` | POST | Purge le state d'un thread |
| `/workflow/status/{thread_id}` | GET | État du workflow pour un thread |

## Flux d'un message

```
Discord message → discord_listener → POST /invoke
  → resolve_agents(channel_id) → team_resolver → team_id
  → load_or_create_state(thread_id, team_id)
  → orchestrator_node(state) ← workflow engine enrichit le contexte
  → decisions → background_tasks.add_task(run_orchestrated)
    → run_agents_parallel (groupe A)
    → auto-dispatch (groupe B, C...) via workflow engine
    → phase complete → human_gate
```

## Thread persistence

- `thread_id = "project-channel-{channel_id}"`
- State sauvegardé dans PostgreSQL via `PostgresSaver`
- Le state contient `_team_id` pour que l'orchestrateur sache quelle équipe
- `!reset` purge le state

## Discord — Commandes

| Commande | Effet |
|---|---|
| `!agent <id> <tâche>` | Route directement vers un agent |
| `!a <alias> <tâche>` | Raccourci |
| `!reset` | Purge le state du channel |
| `!new <nom>` | Nouveau contexte projet |
| `!status` | État de la plateforme |

Aliases : `analyste`, `designer`, `ux`, `architecte`, `archi`, `lead`, `frontend`, `front`, `backend`, `back`, `mobile`, `qa`, `test`, `devops`, `ops`, `docs`, `doc`, `avocat`, `legal`
