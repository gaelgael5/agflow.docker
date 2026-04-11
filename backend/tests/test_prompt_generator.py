from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.schemas.roles import DocumentSummary, RoleSummary  # noqa: E402
from agflow.services import prompt_generator  # noqa: E402


def _make_role() -> RoleSummary:
    from datetime import datetime

    return RoleSummary(
        id="analyst",
        display_name="Analyst",
        description="",
        service_types=[],
        identity_md="Tu es un analyste rigoureux.",
        prompt_orchestrator_md="",
        runtime_config={},
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )


def _make_doc(section: str, name: str, content: str) -> DocumentSummary:
    from datetime import datetime
    from uuid import uuid4

    return DocumentSummary(
        id=uuid4(),
        role_id="analyst",
        section=section,  # type: ignore[arg-type]
        parent_path="",
        name=name,
        content_md=content,
        protected=False,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )


def test_assemble_source_markdown_orders_sections() -> None:
    from agflow.schemas.roles import SectionSummary

    role = _make_role()
    documents = [
        _make_doc("missions", "m1", "Tu transformes sans reformater."),
        _make_doc("roles", "r1", "Tu analyses et extrais."),
        _make_doc("competences", "c1", "Tu maîtrises la déduction logique."),
    ]
    sections = [
        SectionSummary(name="roles", display_name="Rôles", is_native=True, position=0),
        SectionSummary(name="missions", display_name="Missions", is_native=True, position=1),
        SectionSummary(name="competences", display_name="Compétences", is_native=True, position=2),
    ]

    source = prompt_generator.assemble_source_markdown(role, documents, sections)

    assert "# Identité" in source
    assert "Tu es un analyste rigoureux." in source
    identity_idx = source.index("# Identité")
    roles_idx = source.index("## Rôles")
    missions_idx = source.index("## Missions")
    competences_idx = source.index("## Compétences")
    assert identity_idx < roles_idx < missions_idx < competences_idx
    assert "Tu analyses et extrais." in source
    assert "Tu transformes sans reformater." in source
    assert "Tu maîtrises la déduction logique." in source


@pytest.mark.asyncio
async def test_generate_prompts_calls_anthropic_once() -> None:
    role = _make_role()
    docs = [_make_doc("roles", "r1", "Tu analyses.")]

    call_count = {"n": 0}

    class _FakeBlock:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeMessage:
        def __init__(self, text: str) -> None:
            self.content = [_FakeBlock(text)]

    async def _fake_create(**kwargs: object) -> _FakeMessage:
        call_count["n"] += 1
        return _FakeMessage("Il est un assistant qui analyse.")

    fake_messages = type("M", (), {"create": staticmethod(_fake_create)})()
    fake_client = type("FakeClient", (), {"messages": fake_messages})()

    with patch(
        "agflow.services.prompt_generator._get_anthropic_client",
        new=AsyncMock(return_value=fake_client),
    ):
        result = await prompt_generator.generate_prompts(role, docs)

    assert result.prompt_orchestrator_md.startswith("Il est")
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_generate_prompts_raises_if_no_anthropic_key() -> None:
    from agflow.services import secrets_service

    role = _make_role()
    documents: list[DocumentSummary] = []

    async def _raise_missing(names: list[str]) -> dict[str, str]:
        raise secrets_service.SecretNotFoundError("Missing: ANTHROPIC_API_KEY")

    with patch(
        "agflow.services.prompt_generator.secrets_service.resolve_env",
        new=_raise_missing,
    ):
        with pytest.raises(prompt_generator.MissingAnthropicKeyError):
            await prompt_generator.generate_prompts(role, documents)
