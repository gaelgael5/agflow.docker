from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agflow.auth.api_key import require_api_key
from agflow.schemas.agents import AgentDetail, AgentSummary
from agflow.services import agent_generator, agents_service

router = APIRouter(prefix="/api/v1", tags=["public-agents"])


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    _key: dict = require_api_key("agents:read"),
) -> list[AgentSummary]:
    return await agents_service.list_all()


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: UUID,
    _key: dict = require_api_key("agents:read"),
) -> AgentDetail:
    return await agents_service.get_by_id(agent_id)


class GeneratePayload(BaseModel):
    profile_id: UUID | None = None
    secrets: dict[str, str] = Field(default_factory=dict)


@router.post("/agents/{agent_id}/generate")
async def generate_agent(
    agent_id: UUID,
    payload: GeneratePayload | None = None,
    _key: dict = require_api_key("agents:run"),
) -> dict:
    return await agent_generator.generate(
        agent_id,
        profile_id=payload.profile_id if payload else None,
        user_secrets=payload.secrets if payload and payload.secrets else None,
    )


@router.get("/agents/{agent_id}/generated")
async def list_generated_files(
    agent_id: UUID,
    _key: dict = require_api_key("agents:read"),
) -> list[dict]:
    agent = await agents_service.get_by_id(agent_id)
    return await agent_generator.list_generated_files(agent.slug)
