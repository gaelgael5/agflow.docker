from __future__ import annotations

from dataclasses import dataclass

import anthropic
import structlog

from agflow.schemas.roles import DocumentSummary, RoleSummary
from agflow.services import secrets_service

_log = structlog.get_logger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4096


class MissingAnthropicKeyError(Exception):
    pass


@dataclass
class GeneratedPrompts:
    prompt_agent_md: str
    prompt_orchestrator_md: str


def assemble_source_markdown(
    role: RoleSummary, documents: list[DocumentSummary]
) -> str:
    """Concatenate identity + all documents grouped by section into one markdown."""
    parts: list[str] = []
    parts.append("# Identité")
    parts.append("")
    parts.append(role.identity_md or "(identité non renseignée)")
    parts.append("")

    sections = {
        "roles": "Rôles",
        "missions": "Missions",
        "competences": "Compétences",
    }
    for section, title in sections.items():
        docs = [d for d in documents if d.section == section]
        if not docs:
            continue
        parts.append(f"## {title}")
        parts.append("")
        for doc in sorted(docs, key=lambda d: d.name):
            parts.append(f"### {doc.name}")
            parts.append("")
            parts.append(doc.content_md)
            parts.append("")

    return "\n".join(parts)


_AGENT_PROMPT_TEMPLATE = """\
Tu es un assembleur de prompts. Voici la description d'un agent IA \
sous forme d'identité + facettes. Compose un prompt système cohérent à \
la deuxième personne du singulier ("Tu es...", "Tu analyses...") qui \
fusionne tout ce contenu en un texte clair, direct et actionnable. \
N'ajoute pas de méta-commentaire, de titre, ni de balises — retourne \
uniquement le prompt final en markdown.

Source :

{source}
"""

_ORCHESTRATOR_PROMPT_TEMPLATE = """\
Tu reformules un prompt système d'agent IA (écrit à la deuxième personne \
du singulier) en une description à la troisième personne, utilisée par un \
orchestrateur pour décider quand dispatcher cet agent. Garde le sens exact, \
réécris en "Il est...", "Il analyse...", etc. Ne change pas les capacités \
décrites. Retourne uniquement la description finale.

Prompt original :

{source}
"""


async def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY"])
    return anthropic.AsyncAnthropic(api_key=env["ANTHROPIC_API_KEY"])


async def generate_prompts(
    role: RoleSummary, documents: list[DocumentSummary]
) -> GeneratedPrompts:
    """Generate 2nd-person and 3rd-person prompt variants using Claude."""
    try:
        client = await _get_anthropic_client()
    except secrets_service.SecretNotFoundError as exc:
        raise MissingAnthropicKeyError(
            "ANTHROPIC_API_KEY is not set in Module 0 (Secrets)"
        ) from exc

    source = assemble_source_markdown(role, documents)

    _log.info("prompt_generator.agent.start", role_id=role.id)
    agent_response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=DEFAULT_MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": _AGENT_PROMPT_TEMPLATE.format(source=source),
            }
        ],
    )
    agent_text = agent_response.content[0].text  # type: ignore[union-attr]

    _log.info("prompt_generator.orchestrator.start", role_id=role.id)
    orch_response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=DEFAULT_MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": _ORCHESTRATOR_PROMPT_TEMPLATE.format(source=agent_text),
            }
        ],
    )
    orch_text = orch_response.content[0].text  # type: ignore[union-attr]

    _log.info("prompt_generator.done", role_id=role.id)
    return GeneratedPrompts(
        prompt_agent_md=agent_text,
        prompt_orchestrator_md=orch_text,
    )
