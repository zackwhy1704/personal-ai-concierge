import logging
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.api.auth import get_current_tenant
from app.services.billing import BillingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/usage", tags=["usage"])


class MonthlyUsageResponse(BaseModel):
    year: int
    month: int
    total_conversations: int
    total_messages: int
    total_tokens: int
    total_cost: float
    plan: str
    included_conversations: int
    remaining_conversations: int
    overage_conversations: int
    overage_cost: float


class DailyUsageResponse(BaseModel):
    date: str
    conversation_count: int
    message_count: int
    tokens_used: int
    estimated_cost: float


@router.get("/monthly", response_model=MonthlyUsageResponse)
async def get_monthly_usage(
    year: int = Query(default=None),
    month: int = Query(default=None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get monthly usage summary for the current tenant."""
    now = datetime.utcnow()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    usage = await BillingService.get_monthly_usage(db, str(tenant.id), year, month)
    overage = await BillingService.check_overage(db, tenant)

    return MonthlyUsageResponse(
        year=usage["year"],
        month=usage["month"],
        total_conversations=usage["total_conversations"],
        total_messages=usage["total_messages"],
        total_tokens=usage["total_tokens"],
        total_cost=usage["total_cost"],
        plan=tenant.plan.value,
        included_conversations=overage["included"],
        remaining_conversations=overage["remaining"],
        overage_conversations=overage["overage"],
        overage_cost=overage["overage_cost"],
    )


@router.get("/daily", response_model=DailyUsageResponse)
async def get_daily_usage(
    target_date: str = Query(default=None, description="YYYY-MM-DD format"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get usage for a specific day."""
    if target_date is None:
        d = date.today()
    else:
        try:
            d = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    usage = await BillingService.get_daily_usage(db, str(tenant.id), d)
    if not usage:
        return DailyUsageResponse(
            date=d.isoformat(),
            conversation_count=0,
            message_count=0,
            tokens_used=0,
            estimated_cost=0.0,
        )

    return DailyUsageResponse(**usage)
