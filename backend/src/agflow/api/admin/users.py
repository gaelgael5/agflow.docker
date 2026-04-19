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


@router.get(
    "",
    response_model=list[UserSummary],
    summary="List all users",
    description="Returns the complete list of users registered in the platform, ordered by creation date.",
)
async def list_users() -> list[UserSummary]:
    return await users_service.list_all()


@router.get(
    "/{user_id}",
    response_model=UserSummary,
    summary="Get a user by ID",
    description="Returns the full profile of a single user identified by their UUID. Returns 404 if the user does not exist.",
)
async def get_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.get_by_id(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "",
    response_model=UserSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Creates a new user account with the provided email, name, role, scopes, and status. Returns 409 if a user with the same email already exists.",
)
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


@router.patch(
    "/{user_id}",
    response_model=UserSummary,
    summary="Partially update a user",
    description="Updates only the fields provided in the request body for the specified user. Returns 404 if the user does not exist.",
)
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


@router.post(
    "/{user_id}/approve",
    response_model=UserSummary,
    summary="Approve a pending user",
    description="Marks a user as approved, granting them access to the platform. Records the approver's ID for audit purposes.",
)
async def approve_user(user_id: UUID) -> UserSummary:
    try:
        # Temporary self-reference until JWT carries user_id
        return await users_service.approve(user_id, approved_by=user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{user_id}/disable",
    response_model=UserSummary,
    summary="Disable a user account",
    description="Sets the user's status to disabled, preventing them from logging in or using the API. Returns 404 if the user does not exist.",
)
async def disable_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.disable(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{user_id}/enable",
    response_model=UserSummary,
    summary="Re-enable a disabled user account",
    description="Restores the user's status to active, allowing them to log in and use the API again. Returns 404 if the user does not exist.",
)
async def enable_user(user_id: UUID) -> UserSummary:
    try:
        return await users_service.enable(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
    description="Permanently removes the user and all associated data from the platform. Returns 404 if the user does not exist.",
)
async def delete_user(user_id: UUID) -> None:
    try:
        await users_service.delete(user_id)
    except users_service.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
