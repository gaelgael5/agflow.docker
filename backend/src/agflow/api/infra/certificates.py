from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import (
    CertificateCreate,
    CertificateGenerate,
    CertificateSummary,
    CertificateUpdate,
)
from agflow.services import infra_certificates_service

router = APIRouter(
    prefix="/api/infra/certificates",
    tags=["infra-certificates"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[CertificateSummary])
async def list_certificates():
    return await infra_certificates_service.list_all()


@router.post("", response_model=CertificateSummary, status_code=status.HTTP_201_CREATED)
async def create_certificate(payload: CertificateCreate):
    return await infra_certificates_service.create(
        name=payload.name,
        private_key=payload.private_key,
        public_key=payload.public_key,
        passphrase=payload.passphrase,
    )


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_certificate(payload: CertificateGenerate):
    """Generate an SSH key pair (RSA 4096 or Ed25519)."""
    if payload.key_type not in ("rsa", "ed25519"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="key_type must be 'rsa' or 'ed25519'",
        )
    summary, public_key = await infra_certificates_service.generate(
        name=payload.name,
        key_type=payload.key_type,
        passphrase=payload.passphrase,
    )
    return {"certificate": summary, "public_key": public_key}


@router.get("/{cert_id}", response_model=CertificateSummary)
async def get_certificate(cert_id: UUID):
    try:
        return await infra_certificates_service.get_by_id(cert_id)
    except infra_certificates_service.CertificateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{cert_id}/public-key")
async def get_public_key(cert_id: UUID):
    """Return the public key as plain text (for authorized_keys)."""
    try:
        pub = await infra_certificates_service.get_public_key(cert_id)
    except infra_certificates_service.CertificateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not pub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No public key")
    return PlainTextResponse(pub + "\n")


@router.put("/{cert_id}", response_model=CertificateSummary)
async def update_certificate(cert_id: UUID, payload: CertificateUpdate):
    try:
        return await infra_certificates_service.update(cert_id, **payload.model_dump(exclude_unset=True))
    except infra_certificates_service.CertificateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(cert_id: UUID):
    try:
        await infra_certificates_service.delete(cert_id)
    except infra_certificates_service.CertificateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
