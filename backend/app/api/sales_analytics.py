import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.upsell import UpsellAttempt, UpsellOutcome
from app.api.auth import get_current_tenant, verify_admin
from app.services.sales_analytics import SalesAnalyticsService
from app.services.learning import LearningService
from app.services.llm import LLMService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sales", tags=["sales-analytics"])


@router.get("/dashboard")
async def sales_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Full sales dashboard summary."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    funnel = await SalesAnalyticsService.get_conversion_funnel(
        db, str(tenant.id), start_date, end_date
    )
    top_products = await SalesAnalyticsService.get_top_products(
        db, str(tenant.id), start_date, end_date, limit=5
    )
    revenue = await SalesAnalyticsService.get_revenue_attribution(
        db, str(tenant.id), start_date, end_date
    )
    strategy_performance = await SalesAnalyticsService.get_strategy_performance(
        db, str(tenant.id), start_date, end_date
    )

    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": days},
        "funnel": funnel,
        "top_products": top_products,
        "revenue": revenue,
        "strategy_performance": strategy_performance,
    }


@router.get("/conversions")
async def conversion_funnel(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Conversion funnel data."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    return await SalesAnalyticsService.get_conversion_funnel(
        db, str(tenant.id), start_date, end_date
    )


@router.get("/products/performance")
async def product_performance(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Product performance rankings."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    return await SalesAnalyticsService.get_top_products(
        db, str(tenant.id), start_date, end_date, limit
    )


@router.get("/strategies/performance")
async def strategy_performance(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Strategy performance + A/B test results."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    return await SalesAnalyticsService.get_strategy_performance(
        db, str(tenant.id), start_date, end_date
    )


@router.get("/revenue")
async def revenue_attribution(
    start_date: date = Query(default=None),
    end_date: date = Query(default=None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Revenue attribution data."""
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    return await SalesAnalyticsService.get_revenue_attribution(
        db, str(tenant.id), start_date, end_date
    )


@router.get("/cross-sell-patterns")
async def cross_sell_patterns(
    limit: int = Query(default=10, ge=1, le=50),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Discovered cross-sell product pairs."""
    return await SalesAnalyticsService.get_cross_sell_patterns(
        db, str(tenant.id), limit
    )


@router.get("/attempts")
async def list_attempts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    outcome: Optional[UpsellOutcome] = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List recent upsell attempts."""
    query = (
        select(UpsellAttempt)
        .where(UpsellAttempt.tenant_id == tenant.id)
    )
    if outcome:
        query = query.where(UpsellAttempt.outcome == outcome)
    query = query.order_by(desc(UpsellAttempt.presented_at)).offset(offset).limit(limit)

    result = await db.execute(query)
    attempts = result.scalars().all()

    return {
        "attempts": [
            {
                "id": str(a.id),
                "product_id": str(a.product_id),
                "strategy_id": str(a.strategy_id) if a.strategy_id else None,
                "outcome": a.outcome.value,
                "revenue_attributed": a.revenue_attributed,
                "guest_phone": a.guest_phone,
                "session_id": a.session_id,
                "ab_test_group": a.ab_test_group,
                "presented_at": a.presented_at.isoformat() if a.presented_at else None,
                "outcome_at": a.outcome_at.isoformat() if a.outcome_at else None,
            }
            for a in attempts
        ],
        "limit": limit,
        "offset": offset,
    }


class OutcomeUpdate(BaseModel):
    outcome: UpsellOutcome
    revenue: float = 0.0


@router.patch("/attempts/{attempt_id}/outcome")
async def update_attempt_outcome(
    attempt_id: str,
    data: OutcomeUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Manually update an attempt outcome."""
    result = await db.execute(
        select(UpsellAttempt).where(
            UpsellAttempt.id == attempt_id,
            UpsellAttempt.tenant_id == tenant.id,
        )
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt.outcome = data.outcome
    attempt.outcome_at = datetime.utcnow()
    if data.revenue > 0:
        attempt.revenue_attributed = data.revenue
    await db.flush()

    return {"status": "updated", "outcome": attempt.outcome.value}


@router.post("/learning/analyze")
async def trigger_learning_analysis(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Trigger learning loop analysis for this tenant."""
    llm = LLMService()
    learning = LearningService(llm, db)

    performance = await learning.analyze_strategy_performance(str(tenant.id))
    recommendations = await learning.generate_strategy_recommendations(str(tenant.id))

    return {
        "performance": performance,
        "recommendations": recommendations,
    }


@router.post("/learning/optimize")
async def trigger_optimization(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Auto-adjust strategy weights based on performance."""
    llm = LLMService()
    learning = LearningService(llm, db)

    adjustments = await learning.auto_adjust_strategy_weights(str(tenant.id))
    cross_sells = await learning.identify_cross_sell_pairs(str(tenant.id))
    ab_results = await learning.run_ab_test_evaluation(str(tenant.id))

    return {
        "strategy_adjustments": adjustments,
        "cross_sell_discoveries": cross_sells,
        "ab_test_results": ab_results,
    }


@router.post("/learning/run")
async def run_daily_learning(
    _admin: bool = Depends(verify_admin),
    db: AsyncSession = Depends(get_db),
):
    """Run daily learning for all tenants (admin only)."""
    from app.models.tenant import Tenant, TenantStatus
    result = await db.execute(
        select(Tenant).where(Tenant.status == TenantStatus.ACTIVE)
    )
    tenants = result.scalars().all()

    results = {}
    llm = LLMService()
    for tenant in tenants:
        learning = LearningService(llm, db)
        try:
            summary = await learning.run_daily_learning(str(tenant.id))
            results[str(tenant.id)] = summary
        except Exception as e:
            logger.exception(f"Learning failed for tenant {tenant.id}")
            results[str(tenant.id)] = {"error": str(e)}

    await db.commit()
    return {"tenants_processed": len(tenants), "results": results}
