from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.avatars import (
    CharacterCreate,
    CharacterDetail,
    CharacterSummary,
    CharacterUpdate,
    GenerateRequest,
    ThemeCreate,
    ThemeDetail,
    ThemeSummary,
    ThemeUpdate,
)
from agflow.services import ai_providers_service, avatar_storage_service, image_generator
from agflow.services.avatar_storage_service import (
    CharacterNotFoundError,
    DuplicateCharacterError,
    DuplicateImageError,
    DuplicateThemeError,
    ImageNotFoundError,
    ThemeNotFoundError,
)
from agflow.utils.swarm_secrets import get_swarm_secret

router = APIRouter(
    prefix="/api/admin/avatars",
    tags=["admin-avatars"],
    dependencies=[Depends(require_admin)],
)


# ── Thèmes ─────────────────────────────────────────────────


@router.get("", response_model=list[ThemeSummary])
async def list_themes():
    return await avatar_storage_service.list_themes()


@router.post("", response_model=ThemeSummary, status_code=status.HTTP_201_CREATED)
async def create_theme(payload: ThemeCreate):
    try:
        return await avatar_storage_service.create_theme(
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
            provider=payload.provider,
            size=payload.size,
            quality=payload.quality,
            style=payload.style,
        )
    except DuplicateThemeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{theme}", response_model=ThemeDetail)
async def get_theme(theme: str):
    try:
        return await avatar_storage_service.get_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{theme}", response_model=ThemeDetail)
async def update_theme(theme: str, payload: ThemeUpdate):
    try:
        return await avatar_storage_service.update_theme(theme, **payload.model_dump(exclude_unset=True))
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{theme}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_theme(theme: str):
    try:
        await avatar_storage_service.delete_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Personnages ────────────────────────────────────────────


@router.get("/{theme}/characters", response_model=list[CharacterSummary])
async def list_characters(theme: str):
    try:
        return await avatar_storage_service.list_characters(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{theme}/characters", response_model=CharacterSummary, status_code=status.HTTP_201_CREATED)
async def create_character(theme: str, payload: CharacterCreate):
    try:
        return await avatar_storage_service.create_character(
            theme_slug=theme,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
        )
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateCharacterError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{theme}/characters/{char}", response_model=CharacterDetail)
async def get_character(theme: str, char: str):
    try:
        return await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{theme}/characters/{char}", response_model=CharacterDetail)
async def update_character(theme: str, char: str, payload: CharacterUpdate):
    try:
        return await avatar_storage_service.update_character(
            theme, char, **payload.model_dump(exclude_unset=True)
        )
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{theme}/characters/{char}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(theme: str, char: str):
    try:
        await avatar_storage_service.delete_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Images ─────────────────────────────────────────────────


@router.get("/{theme}/characters/{char}/images")
async def list_images(theme: str, char: str):
    return await avatar_storage_service.list_images(theme, char)


@router.post("/{theme}/characters/{char}/generate")
async def generate_image(theme: str, char: str, payload: GenerateRequest | None = None):
    try:
        theme_detail = await avatar_storage_service.get_theme(theme)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        char_detail = await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    api_key = (payload.api_key if payload else None) or ""
    if not api_key:
        api_key = await ai_providers_service.resolve_api_key("image_generation", theme_detail.provider)
    if not api_key:
        api_key = get_swarm_secret("openai_api_key", env_fallback="OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune clé API trouvée. Configurez le provider dans AI Providers ou ajoutez OPENAI_API_KEY dans les secrets.",
        )

    prompt = image_generator.build_prompt(theme_detail.prompt, char_detail.display_name, char_detail.prompt)
    provider = image_generator.get_provider(theme_detail.provider, api_key)
    try:
        image_bytes = await provider.generate(
            prompt=prompt,
            size=theme_detail.size,
            quality=theme_detail.quality,
            style=theme_detail.style,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    number = await avatar_storage_service.save_image(theme, char, image_bytes)
    return {"number": number, "size_bytes": len(image_bytes)}


@router.post("/{theme}/characters/{char}/upload")
async def upload_image(theme: str, char: str, file: UploadFile):
    try:
        await avatar_storage_service.get_character(theme, char)
    except CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    image_bytes = await file.read()
    try:
        number = await avatar_storage_service.save_image(theme, char, image_bytes)
    except DuplicateImageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"number": number, "size_bytes": len(image_bytes)}


@router.get("/{theme}/characters/{char}/images/{n}")
async def get_image(theme: str, char: str, n: int):
    try:
        image_bytes = await avatar_storage_service.get_image_bytes(theme, char, n)
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(content=image_bytes, media_type="image/png")


@router.delete("/{theme}/characters/{char}/images/{n}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(theme: str, char: str, n: int):
    try:
        await avatar_storage_service.delete_image(theme, char, n)
    except (ImageNotFoundError, CharacterNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{theme}/characters/{char}/select/{n}", status_code=status.HTTP_204_NO_CONTENT)
async def select_image(theme: str, char: str, n: int):
    try:
        await avatar_storage_service.select_image(theme, char, n)
    except (ImageNotFoundError, CharacterNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
