# Canaux de communication — channels.py

Architecture factorisée pour la communication agents ↔ humains.

## Interface MessageChannel

```python
class MessageChannel(ABC):
    async def send(channel_id, message) → bool
    async def ask(channel_id, agent_name, question, timeout) → {answered, response, author, timed_out}
    async def approve(channel_id, agent_name, summary, timeout) → {approved, response, reviewer, timed_out}
    # + wrappers *_sync() automatiques
```

## Implémentations

| Canal | Classe | Envoi | Réception |
|---|---|---|---|
| Discord | `DiscordChannel` | REST API Discord | Polling messages |
| Email | `EmailChannel` | SMTP | IMAP polling |
| Telegram | (à venir) | Bot API | Webhook/polling |

## Utilisation

```python
from agents.shared.channels import get_channel, get_default_channel
ch = get_default_channel()  # lit DEFAULT_CHANNEL dans .env
await ch.send("123456", "Hello")
await ch.approve("123456", "Lead Dev", "PRD validé ?")
```

## Modules branchés sur channels.py

- `gateway.py` → `post_to_channel()` (remplace l'ancien `post_to_discord`)
- `human_gate.py` → délègue à `channels.approve()`
- `agent_conversation.py` → délègue à `channels.ask()`
