from __future__ import annotations

import json

import anthropic
import structlog
from pydantic import BaseModel, Field

from agflow.services import secrets_service

_log = structlog.get_logger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"
_MAX_TOKENS = 4096


class MissingAnthropicKeyError(Exception):
    pass


class GenerationFailedError(Exception):
    pass


class GeneratedDockerfile(BaseModel):
    """Strict shape returned to the frontend after an LLM generation pass."""

    dockerfile: str = Field(description="Content of the Dockerfile")
    entrypoint_sh: str = Field(description="Content of entrypoint.sh")
    run_cmd_md: str = Field(description="Content of run.cmd.md documentation")
    reasoning: str = Field(
        default="",
        description="Short plain-text summary of the choices the LLM made",
    )


_SYSTEM_PROMPT = """\
You are an expert DevOps engineer specialized in creating Docker images for \
AI CLI agents (claude-code, aider, codex, goose, etc.). Given a short \
natural-language description of the agent the user wants, you generate \
three standard files in strict JSON:

1. **Dockerfile** — a minimal, well-documented Dockerfile that:
   - starts from a slim base image (python:3.12-slim or node:20-alpine \
     depending on the CLI),
   - installs only what is needed (git by default, plus any extras the user \
     mentions),
   - creates a non-root `agflow` user and switches to it,
   - declares the 4 standardized volumes: /app (workspace), /app/skills, \
     /app/config, /app/output,
   - sets ENTRYPOINT ["/app/entrypoint.sh"].

2. **entrypoint.sh** — a POSIX sh script (not bash) that:
   - reads a single JSON task from stdin with fields task_id, instruction, \
     timeout_seconds, model,
   - emits newline-delimited JSON events on stdout with shape \
     {"type":"progress"|"result","task_id":"...", ...},
   - handles SIGTERM and prints a final `{"type":"shutdown"}` event,
   - exits 0 on success, 1 on error.

3. **run.cmd.md** — a concise markdown doc that:
   - explains what the agent does (1 line),
   - shows the `docker run` command with the normalized volumes mounted,
   - lists the environment variables the container expects,
   - describes the stdin/stdout contract in 3-5 lines.

Respond with a SINGLE JSON object matching this schema exactly, no \
markdown fences, no prose outside the JSON:
{
  "dockerfile": "...",
  "entrypoint_sh": "...",
  "run_cmd_md": "...",
  "reasoning": "1-3 sentences explaining your choices"
}
"""


async def _get_client() -> anthropic.AsyncAnthropic:
    try:
        env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY"])
    except secrets_service.SecretNotFoundError as exc:
        raise MissingAnthropicKeyError(
            "ANTHROPIC_API_KEY is not set in Module 0 (Secrets)"
        ) from exc
    return anthropic.AsyncAnthropic(api_key=env["ANTHROPIC_API_KEY"])


def _parse_response(text: str) -> GeneratedDockerfile:
    # The LLM is instructed to return raw JSON but sometimes wraps in
    # ```json ... ``` fences. Strip them defensively.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        if cleaned.startswith("json\n"):
            cleaned = cleaned[5:]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GenerationFailedError(
            f"LLM returned invalid JSON: {exc}. First 200 chars: {cleaned[:200]}"
        ) from exc
    try:
        return GeneratedDockerfile(**data)
    except Exception as exc:  # noqa: BLE001
        raise GenerationFailedError(
            f"LLM response does not match schema: {exc}"
        ) from exc


async def generate(description: str) -> GeneratedDockerfile:
    """Generate a Dockerfile + entrypoint.sh + run.cmd.md from a description."""
    client = await _get_client()
    _log.info("dockerfile_chat.generate.start", description_len=len(description))

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Agent description:\n\n{description}",
            }
        ],
    )
    text = response.content[0].text  # type: ignore[union-attr]
    parsed = _parse_response(text)
    _log.info(
        "dockerfile_chat.generate.done",
        dockerfile_len=len(parsed.dockerfile),
        entrypoint_len=len(parsed.entrypoint_sh),
        run_cmd_len=len(parsed.run_cmd_md),
    )
    return parsed
