import logging
from typing import Optional
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db
from app.models.promo_code import PromoCode
from app.api.auth import verify_admin

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/promo", tags=["promo"])

stripe.api_key = settings.stripe_secret_key


async def _ensure_table(db: AsyncSession):
    """Ensure promo_codes table exists (safe to call multiple times)."""
    try:
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(50) UNIQUE NOT NULL,
                description VARCHAR(255),
                trial_days INTEGER NOT NULL DEFAULT 30,
                max_redemptions INTEGER,
                times_redeemed INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                expires_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                stripe_coupon_id VARCHAR(100),
                stripe_promo_id VARCHAR(100)
            )
        """))
        # Add new columns if table already existed without them
        for col, coltype in [("stripe_coupon_id", "VARCHAR(100)"), ("stripe_promo_id", "VARCHAR(100)")]:
            try:
                await db.execute(text(f"ALTER TABLE promo_codes ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        await db.flush()
    except Exception:
        pass


# ── Schemas ──────────────────────────────────

class PromoCodeCreate(BaseModel):
    code: str
    description: Optional[str] = None
    trial_days: int = 30
    max_redemptions: Optional[int] = None
    expires_at: Optional[str] = None  # ISO format


class PromoCodeResponse(BaseModel):
    id: str
    code: str
    description: Optional[str]
    trial_days: int
    max_redemptions: Optional[int]
    times_redeemed: int
    is_active: bool
    expires_at: Optional[str]
    created_at: str
    stripe_coupon_id: Optional[str] = None
    stripe_promo_id: Optional[str] = None


class PromoValidationResponse(BaseModel):
    valid: bool
    code: str
    trial_days: int = 0
    message: str


# ── Admin endpoints ──────────────────────────

@router.post("", response_model=PromoCodeResponse)
async def create_promo_code(
    data: PromoCodeCreate,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """Create a new promo code (admin only).

    Creates both a local record and a Stripe Coupon + Promotion Code.
    The promo code appears on the Stripe Checkout page — customers
    enter it alongside their credit card info.
    """
    await _ensure_table(db)
    code = data.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    existing = await db.execute(select(PromoCode).where(PromoCode.code == code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Promo code already exists")

    expires_at = None
    if data.expires_at:
        try:
            expires_at = datetime.fromisoformat(data.expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format")

    # Create Stripe Coupon (100% off for trial_days duration)
    stripe_coupon_id = None
    stripe_promo_id = None
    try:
        coupon = stripe.Coupon.create(
            percent_off=100,
            duration="once",
            name=f"{code} - {data.trial_days}-day free trial",
            metadata={"promo_code": code, "trial_days": str(data.trial_days)},
        )
        stripe_coupon_id = coupon.id

        # Create Stripe Promotion Code (the customer-facing code)
        promo_code_params = {
            "coupon": coupon.id,
            "code": code,
            "metadata": {"trial_days": str(data.trial_days)},
        }
        if data.max_redemptions:
            promo_code_params["max_redemptions"] = data.max_redemptions
        if expires_at:
            promo_code_params["expires_at"] = int(expires_at.timestamp())

        stripe_promo = stripe.PromotionCode.create(**promo_code_params)
        stripe_promo_id = stripe_promo.id
        logger.info(f"Created Stripe coupon {stripe_coupon_id} and promo {stripe_promo_id} for {code}")
    except Exception as e:
        logger.warning(f"Failed to create Stripe coupon/promo for {code}: {e}")
        # Still create the local record — Stripe integration is best-effort

    promo = PromoCode(
        code=code,
        description=data.description,
        trial_days=data.trial_days,
        max_redemptions=data.max_redemptions,
        expires_at=expires_at,
        stripe_coupon_id=stripe_coupon_id,
        stripe_promo_id=stripe_promo_id,
    )
    db.add(promo)
    await db.flush()

    return _to_response(promo)


@router.get("", response_model=list[PromoCodeResponse])
async def list_promo_codes(
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """List all promo codes (admin only)."""
    await _ensure_table(db)
    result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
    return [_to_response(p) for p in result.scalars().all()]


@router.patch("/{promo_id}/deactivate")
async def deactivate_promo_code(
    promo_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: bool = Depends(verify_admin),
):
    """Deactivate a promo code (admin only). Also deactivates in Stripe."""
    result = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    promo.is_active = False
    await db.flush()

    # Deactivate in Stripe
    if promo.stripe_promo_id:
        try:
            stripe.PromotionCode.modify(promo.stripe_promo_id, active=False)
        except Exception as e:
            logger.warning(f"Failed to deactivate Stripe promo {promo.stripe_promo_id}: {e}")

    return {"status": "deactivated", "code": promo.code}


# ── Public validation endpoint ───────────────

@router.post("/validate", response_model=PromoValidationResponse)
async def validate_promo_code(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Validate a promo code. No auth required — just checks validity."""
    await _ensure_table(db)
    code = (data.get("code") or "").strip().upper()
    if not code:
        return PromoValidationResponse(
            valid=False, code=code, message="Please enter a promo code"
        )

    result = await db.execute(select(PromoCode).where(PromoCode.code == code))
    promo = result.scalar_one_or_none()

    if not promo:
        return PromoValidationResponse(
            valid=False, code=code, message="Invalid promo code"
        )

    if not promo.is_valid():
        if not promo.is_active:
            msg = "This promo code is no longer active"
        elif promo.expires_at and datetime.utcnow() > promo.expires_at:
            msg = "This promo code has expired"
        else:
            msg = "This promo code has reached its redemption limit"
        return PromoValidationResponse(valid=False, code=code, message=msg)

    return PromoValidationResponse(
        valid=True,
        code=code,
        trial_days=promo.trial_days,
        message=f"Valid! {promo.trial_days}-day free trial will be applied",
    )


def _to_response(promo: PromoCode) -> PromoCodeResponse:
    return PromoCodeResponse(
        id=str(promo.id),
        code=promo.code,
        description=promo.description,
        trial_days=promo.trial_days,
        max_redemptions=promo.max_redemptions,
        times_redeemed=promo.times_redeemed,
        is_active=promo.is_active,
        expires_at=promo.expires_at.isoformat() if promo.expires_at else None,
        created_at=promo.created_at.isoformat(),
        stripe_coupon_id=promo.stripe_coupon_id,
        stripe_promo_id=promo.stripe_promo_id,
    )
