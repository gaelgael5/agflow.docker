from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.users import UserCreate, UserSummary, UserUpdate
from agflow.services import users_service

router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[UserSummary])
async def list_users() -> list[UserSummary]:
    return await users_service.list_all()


@router.get("/{user_id}", response_model=UserSummary)
async def get_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.get_by_id(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> UserSummary:
    try:
        return await users_service.create(
            email=payload.email,
            name=payload.name,
            role=payload.role,
            scopes=payload.scopes,
            status=payload.status,
        )
    except users_service.DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.patch("/{user_id}", response_model=UserSummary)
async def update_user(user_id: UUID, payload: UserUpdate) -> UserSummary:
    try:
        return await users_service.update(
            user_id,
            **payload.model_dump(exclude_unset=True),
        )
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{user_id}/approve", response_model=UserSummary)
async def approve_user(user_id: UUID) -> UserSummary:
    try:
        # Temporary self-reference until JWT carries user_id
        return await users_service.approve(user_id, approved_by=user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{user_id}/disable", response_model=UserSummary)
async def disable_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.disable(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{user_id}/enable", response_model=UserSummary)
async def enable_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.enable(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: UUID) -> None:
    try:
        await users_service.delete(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
