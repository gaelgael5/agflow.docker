from __future__ import annotations

from dataclasses import dataclass

import anthropic
import structlog

from agflow.schemas.roles import DocumentSummary, RoleSummary, SectionSummary
from agflow.services import secrets_service

_log = structlog.get_logger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4096


class MissingAnthropicKeyError(Exception):
    pass


@dataclass
class GeneratedPrompts:
    prompt_orchestrator_md: str


def assemble_source_markdown(
    role: RoleSummary,
    documents: list[DocumentSummary],
    sections: list[SectionSummary] | None = None,
) -> str:
    """Concatenate identity + all documents grouped by section into one markdown.

    This is the 2nd-person source-of-truth. It's used both as input to
    `generate_prompts` (to produce the 3rd-person orchestrator description) and
    as the final "agent prompt" injected into the agent container at launch.

    The `sections` argument, when provided, dictates the ordering and display
    names of the section headers. If omitted, sections are inferred from the
    documents themselves (sorted alphabetically, raw names as headers).
    """
    parts: list[str] = []
    parts.append("# Identité")
    parts.append("")
    parts.append(role.identity_md or "(identité non renseignée)")
    parts.append("")

    if sections is not None:
        ordered_sections = [(s.name, s.display_name) for s in sections]
    else:
        seen: dict[str, str] = {}
        for d in documents:
            seen.setdefault(d.section, d.section.capitalize())
        ordered_sections = sorted(seen.items())

    for section_name, title in ordered_sections:
        docs = [d for d in documents if d.section == section_name]
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


_ORCHESTRATOR_PROMPT_TEMPLATE = """\
Tu reformules la description d'un agent IA (écrite à la deuxième personne \
du singulier : identité + rôles + missions + compétences) en une description \
à la troisième personne, utilisée par un orchestrateur pour décider quand \
dispatcher cet agent. Garde le sens exact, réécris en "Il est...", \
"Il analyse...", etc. Ne change pas les capacités décrites. Retourne \
uniquement la description finale en markdown, sans méta-commentaire ni balises.

Source :

{source}
"""


async def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY"])
    return anthropic.AsyncAnthropic(api_key=env["ANTHROPIC_API_KEY"])


async def generate_prompts(
    role: RoleSummary,
    documents: list[DocumentSummary],
    sections: list[SectionSummary] | None = None,
) -> GeneratedPrompts:
    """Generate the 3rd-person orchestrator description from the assembled source."""
    try:
        client = await _get_anthropic_client()
    except secrets_service.SecretNotFoundError as exc:
        raise MissingAnthropicKeyError(
            "ANTHROPIC_API_KEY is not set in Module 0 (Secrets)"
        ) from exc

    source = assemble_source_markdown(role, documents, sections)

    _log.info("prompt_generator.orchestrator.start", role_id=role.id)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=DEFAULT_MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": _ORCHESTRATOR_PROMPT_TEMPLATE.format(source=source),
            }
        ],
    )
    orch_text = response.content[0].text  # type: ignore[union-attr]

    _log.info("prompt_generator.done", role_id=role.id)
    return GeneratedPrompts(prompt_orchestrator_md=orch_text)
