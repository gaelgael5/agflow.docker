from __future__ import annotations

import base64
from abc import ABC, abstractmethod

import structlog

_log = structlog.get_logger(__name__)


class ImageProvider(ABC):
    """Interface pour les providers de génération d'images."""

    @abstractmethod
    async def generate(self, prompt: str, size: str, quality: str, style: str) -> bytes:
        """Génère une image et retourne les bytes PNG."""
        ...


class DallE3Provider(ImageProvider):
    """Provider DALL-E 3 via l'API OpenAI."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def generate(self, prompt: str, size: str, quality: str, style: str) -> bytes:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            style=style,
            n=1,
            response_format="b64_json",
        )
        image_b64 = response.data[0].b64_json
        assert image_b64 is not None
        _log.info("image_generator.generated", provider="dall-e-3", size=size, quality=quality)
        return base64.b64decode(image_b64)


PROVIDERS: dict[str, type[ImageProvider]] = {
    "dall-e-3": DallE3Provider,
}


def get_provider(provider_name: str, api_key: str) -> ImageProvider:
    """Instancie un provider par nom."""
    cls = PROVIDERS.get(provider_name)
    if not cls:
        raise ValueError(f"Unknown provider: {provider_name}. Available: {list(PROVIDERS.keys())}")
    return cls(api_key=api_key)


def build_prompt(theme_prompt: str, character_name: str, character_prompt: str) -> str:
    """Assemble le prompt final à envoyer au provider."""
    return f"{theme_prompt}\n\nCharacter: **{character_name}**.\n{character_prompt}"
