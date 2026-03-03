import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant, PlanType, TenantStatus
from app.api.auth import (
    verify_admin,
    get_current_tenant,
    generate_api_key,
    hash_api_key,
    create_jwt_token,
)
from app.services.billing import BillingService
from app.pricing import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants", tags=["tenants"])


class TenantCreate(BaseModel):
    name: str
    slug: str
    plan: PlanType = PlanType.STARTER
    currency: str = "MYR"
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    admin_phone_numbers: Optional[str] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[PlanType] = None
    status: Optional[TenantStatus] = None
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    admin_phone_numbers: Optional[str] = None


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    currency: str = "MYR"
    status: str
    whatsapp_phone_number_id: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class TenantCreateResponse(BaseModel):
    tenant: TenantResponse
    api_key: str  # only returned on creation
    jwt_token: str


@router.post("", response_model=TenantCreateResponse)
async def create_tenant(
    data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """Create a new tenant (admin only)."""
    # Validate currency
    currency = data.currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}. Supported: {', '.join(SUPPORTED_CURRENCIES)}")

    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already in use")

    api_key = generate_api_key()

    tenant = Tenant(
        name=data.name,
        slug=data.slug,
        api_key=api_key[:16],  # store prefix for identification
        api_key_hash=hash_api_key(api_key),
        plan=data.plan,
        currency=currency,
        status=TenantStatus.ONBOARDING,
        whatsapp_phone_number_id=data.whatsapp_phone_number_id,
        whatsapp_business_account_id=data.whatsapp_business_account_id,
        whatsapp_access_token=data.whatsapp_access_token,
        admin_phone_numbers=data.admin_phone_numbers,
    )
    db.add(tenant)
    await db.flush()

    jwt_token = create_jwt_token(str(tenant.id))

    return TenantCreateResponse(
        tenant=TenantResponse(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            plan=tenant.plan.value,
            currency=tenant.currency,
            status=tenant.status.value,
            whatsapp_phone_number_id=tenant.whatsapp_phone_number_id,
            created_at=tenant.created_at.isoformat(),
        ),
        api_key=api_key,
        jwt_token=jwt_token,
    )


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get current tenant's info."""
    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        plan=tenant.plan.value,
        currency=tenant.currency,
        status=tenant.status.value,
        whatsapp_phone_number_id=tenant.whatsapp_phone_number_id,
        created_at=tenant.created_at.isoformat(),
    )


@router.patch("/me", response_model=TenantResponse)
async def update_my_tenant(
    data: TenantUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update current tenant's settings."""
    if data.name is not None:
        tenant.name = data.name
    if data.whatsapp_phone_number_id is not None:
        tenant.whatsapp_phone_number_id = data.whatsapp_phone_number_id
    if data.whatsapp_business_account_id is not None:
        tenant.whatsapp_business_account_id = data.whatsapp_business_account_id
    if data.whatsapp_access_token is not None:
        tenant.whatsapp_access_token = data.whatsapp_access_token
    if data.admin_phone_numbers is not None:
        tenant.admin_phone_numbers = data.admin_phone_numbers

    tenant.updated_at = datetime.utcnow()
    await db.flush()

    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        plan=tenant.plan.value,
        currency=tenant.currency,
        status=tenant.status.value,
        whatsapp_phone_number_id=tenant.whatsapp_phone_number_id,
        created_at=tenant.created_at.isoformat(),
    )


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """List all tenants (admin only)."""
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()
    return [
        TenantResponse(
            id=str(t.id),
            name=t.name,
            slug=t.slug,
            plan=t.plan.value,
            currency=t.currency,
            status=t.status.value,
            whatsapp_phone_number_id=t.whatsapp_phone_number_id,
            created_at=t.created_at.isoformat(),
        )
        for t in tenants
    ]


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def admin_update_tenant(
    tenant_id: str,
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """Update any tenant by ID (admin only)."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name is not None:
        tenant.name = data.name
    if data.plan is not None:
        tenant.plan = data.plan
    if data.status is not None:
        tenant.status = data.status
    if data.whatsapp_phone_number_id is not None:
        tenant.whatsapp_phone_number_id = data.whatsapp_phone_number_id
    if data.whatsapp_business_account_id is not None:
        tenant.whatsapp_business_account_id = data.whatsapp_business_account_id
    if data.whatsapp_access_token is not None:
        tenant.whatsapp_access_token = data.whatsapp_access_token
    if data.admin_phone_numbers is not None:
        tenant.admin_phone_numbers = data.admin_phone_numbers

    tenant.updated_at = datetime.utcnow()
    await db.flush()

    return TenantResponse(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        plan=tenant.plan.value,
        currency=tenant.currency,
        status=tenant.status.value,
        whatsapp_phone_number_id=tenant.whatsapp_phone_number_id,
        created_at=tenant.created_at.isoformat(),
    )


@router.post("/{tenant_id}/token")
async def get_tenant_token(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """Generate a JWT token for a specific tenant (admin only)."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    jwt_token = create_jwt_token(str(tenant.id))
    return {"jwt_token": jwt_token, "tenant_id": str(tenant.id), "tenant_name": tenant.name}


@router.post("/me/activate")
async def activate_tenant(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Activate tenant after onboarding is complete."""
    if not tenant.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=400,
            detail="WhatsApp phone number ID must be configured before activation",
        )

    tenant.status = TenantStatus.ACTIVE
    tenant.updated_at = datetime.utcnow()
    await db.flush()

    return {"status": "active", "message": "Tenant activated successfully"}
