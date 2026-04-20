from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agflow.auth.dependencies import require_operator as require_admin
from agflow.generators import get_generator
from agflow.services import product_catalog_service, product_instances_service, secrets_service

router = APIRouter(
    prefix="/api/admin/product-instances",
    tags=["admin-generations"],
    dependencies=[Depends(require_admin)],
)


class GenerateRequest(BaseModel):
    generator: str = "docker_compose"
    options: dict | None = None


@router.post(
    "/{project_id}/{instance_id}/generate",
    summary="Generate deployment artifacts for an instance",
)
async def generate_artifacts(
    project_id: str,
    instance_id: str,
    payload: GenerateRequest,
):
    try:
        instance = product_instances_service.get_by_id(project_id, instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        product = product_catalog_service.get_by_id(instance.catalog_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Resolve secrets
    secret_names = [s["name"] for s in product.recipe.get("secrets_required", [])]
    resolved_secrets: dict[str, str] = {}
    if secret_names:
        try:
            resolved_secrets = await secrets_service.resolve_env(secret_names)
        except secrets_service.SecretNotFoundError:
            # Partial resolution — resolve individually
            for name in secret_names:
                try:
                    result = await secrets_service.resolve_env([name])
                    resolved_secrets.update(result)
                except secrets_service.SecretNotFoundError:
                    resolved_secrets[name] = ""

    try:
        generator = get_generator(payload.generator)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    artifacts = generator.generate(
        recipe=product.recipe,
        instance_name=instance.instance_name,
        resolved_secrets=resolved_secrets,
        resolved_variables=instance.variables,
        options=payload.options,
    )

    return {
        "generator": payload.generator,
        "instance_name": instance.instance_name,
        "artifact_count": len(artifacts),
        "artifacts": [
            {"filename": a.filename, "artifact_type": a.artifact_type, "size": len(a.content)}
            for a in artifacts
        ],
    }


@router.post(
    "/{project_id}/{instance_id}/generate/download",
    summary="Generate and download artifacts as a ZIP",
)
async def generate_and_download(
    project_id: str,
    instance_id: str,
    payload: GenerateRequest,
):
    try:
        instance = product_instances_service.get_by_id(project_id, instance_id)
    except product_instances_service.InstanceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    try:
        product = product_catalog_service.get_by_id(instance.catalog_id)
    except product_catalog_service.ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Resolve secrets
    secret_names = [s["name"] for s in product.recipe.get("secrets_required", [])]
    resolved_secrets: dict[str, str] = {}
    if secret_names:
        try:
            resolved_secrets = await secrets_service.resolve_env(secret_names)
        except secrets_service.SecretNotFoundError:
            for name in secret_names:
                try:
                    result = await secrets_service.resolve_env([name])
                    resolved_secrets.update(result)
                except secrets_service.SecretNotFoundError:
                    resolved_secrets[name] = ""

    try:
        generator = get_generator(payload.generator)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    artifacts = generator.generate(
        recipe=product.recipe,
        instance_name=instance.instance_name,
        resolved_secrets=resolved_secrets,
        resolved_variables=instance.variables,
        options=payload.options,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for a in artifacts:
            zf.writestr(a.filename, a.content)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{instance.instance_name}-{payload.generator}.zip"',
        },
    )
