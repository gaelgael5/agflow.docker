from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

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
from agflow.services import ai_providers_service, avatar_service, image_generator

router = APIRouter(
    prefix="/api/admin/avatars",
    tags=["admin-avatars"],
    dependencies=[Depends(require_admin)],
)


# ── Thèmes ─────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[ThemeSummary],
    summary="List all avatar themes",
)
async def list_themes():
    return avatar_service.list_themes()


@router.post(
    "",
    response_model=ThemeSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create an avatar theme",
)
async def create_theme(payload: ThemeCreate):
    try:
        return avatar_service.create_theme(
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
            provider=payload.provider,
            size=payload.size,
            quality=payload.quality,
            style=payload.style,
        )
    except avatar_service.DuplicateThemeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{theme}",
    response_model=ThemeDetail,
    summary="Get theme detail with characters",
)
async def get_theme(theme: str):
    try:
        return avatar_service.get_theme(theme)
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/{theme}",
    response_model=ThemeDetail,
    summary="Update theme metadata and prompt",
)
async def update_theme(theme: str, payload: ThemeUpdate):
    try:
        return avatar_service.update_theme(theme, **payload.model_dump(exclude_unset=True))
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{theme}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete theme and all its content",
)
async def delete_theme(theme: str):
    try:
        avatar_service.delete_theme(theme)
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Personnages ────────────────────────────────────────────


@router.get(
    "/{theme}/characters",
    response_model=list[CharacterSummary],
    summary="List characters in a theme",
)
async def list_characters(theme: str):
    try:
        avatar_service.get_theme(theme)
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [
        avatar_service.get_character_summary(theme, c)
        for c in avatar_service._list_char_slugs(theme)
    ]


@router.post(
    "/{theme}/characters",
    response_model=CharacterSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a character in a theme",
)
async def create_character(theme: str, payload: CharacterCreate):
    try:
        return avatar_service.create_character(
            theme_slug=theme,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            prompt=payload.prompt,
        )
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except avatar_service.DuplicateCharacterError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{theme}/characters/{char}",
    response_model=CharacterDetail,
    summary="Get character detail with images",
)
async def get_character(theme: str, char: str):
    try:
        return avatar_service.get_character(theme, char)
    except avatar_service.CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/{theme}/characters/{char}",
    response_model=CharacterDetail,
    summary="Update character metadata and prompt",
)
async def update_character(theme: str, char: str, payload: CharacterUpdate):
    try:
        return avatar_service.update_character(
            theme, char, **payload.model_dump(exclude_unset=True)
        )
    except avatar_service.CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{theme}/characters/{char}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete character and all its images",
)
async def delete_character(theme: str, char: str):
    try:
        avatar_service.delete_character(theme, char)
    except avatar_service.CharacterNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Images ─────────────────────────────────────────────────


@router.get(
    "/{theme}/characters/{char}/images",
    summary="List images for a character",
)
async def list_images(theme: str, char: str):
    return avatar_service.list_images(theme, char)


@router.post(
    "/{theme}/characters/{char}/generate",
    summary="Generate an image via the provider",
)
async def generate_image(
    theme: str, char: str, payload: GenerateRequest | None = None
):
    try:
        theme_detail = avatar_service.get_theme(theme)
    except avatar_service.ThemeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    try:
        char_detail = avatar_service.get_character(theme, char)
    except avatar_service.CharacterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    # Resolve API key: body > AI providers config > env
    api_key = (payload.api_key if payload else None) or ""
    if not api_key:
        api_key = await ai_providers_service.resolve_api_key(
            "image_generation", theme_detail.provider,
        )
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune clé API trouvée. Configurez le provider dans AI Providers ou ajoutez OPENAI_API_KEY dans les secrets.",
        )

    prompt = image_generator.build_prompt(
        theme_detail.prompt, char_detail.display_name, char_detail.prompt
    )
    provider = image_generator.get_provider(theme_detail.provider, api_key)

    try:
        image_bytes = await provider.generate(
            prompt=prompt,
            size=theme_detail.size,
            quality=theme_detail.quality,
            style=theme_detail.style,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    number = avatar_service.save_image(theme, char, image_bytes)
    return {"number": number, "size_bytes": len(image_bytes)}


@router.post(
    "/{theme}/characters/{char}/upload",
    summary="Upload an image file",
)
async def upload_image(theme: str, char: str, file: UploadFile):
    try:
        avatar_service.get_character(theme, char)
    except avatar_service.CharacterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    image_bytes = await file.read()
    try:
        number = avatar_service.save_image(theme, char, image_bytes)
    except avatar_service.DuplicateImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return {"number": number, "size_bytes": len(image_bytes)}


@router.get(
    "/{theme}/characters/{char}/images/{n}",
    summary="Serve an image file",
)
async def get_image(theme: str, char: str, n: int):
    try:
        path = avatar_service.get_image_path(theme, char, n)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return FileResponse(path, media_type="image/png")


@router.delete(
    "/{theme}/characters/{char}/images/{n}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an image",
)
async def delete_image(theme: str, char: str, n: int):
    try:
        avatar_service.delete_image(theme, char, n)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{theme}/characters/{char}/select/{n}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Select image as active avatar",
)
async def select_image(theme: str, char: str, n: int):
    try:
        avatar_service.select_image(theme, char, n)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
