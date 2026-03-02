import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.upsell import UpsellAttempt, UpsellOutcome
from app.models.product import Product
from app.models.upsell import UpsellStrategy
from app.models.sales_analytics import SalesMetricDaily

logger = logging.getLogger(__name__)


class SalesAnalyticsService:
    """Aggregation and analytics for sales performance."""

    @staticmethod
    async def get_conversion_funnel(
        db: AsyncSession,
        tenant_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """Return funnel: attempts -> interest -> clicks -> conversions."""
        base_filter = and_(
            UpsellAttempt.tenant_id == tenant_id,
            func.date(UpsellAttempt.presented_at) >= start_date,
            func.date(UpsellAttempt.presented_at) <= end_date,
        )

        total = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(base_filter)
        ) or 0

        interest = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter,
                UpsellAttempt.outcome.in_([
                    UpsellOutcome.INTEREST_SHOWN,
                    UpsellOutcome.CLICKED,
                    UpsellOutcome.CONVERTED,
                ]),
            )
        ) or 0

        clicks = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter,
                UpsellAttempt.outcome.in_([
                    UpsellOutcome.CLICKED,
                    UpsellOutcome.CONVERTED,
                ]),
            )
        ) or 0

        conversions = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter,
                UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
            )
        ) or 0

        revenue = await db.scalar(
            select(func.coalesce(func.sum(UpsellAttempt.revenue_attributed), 0)).where(
                base_filter,
                UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
            )
        ) or 0

        return {
            "total_attempts": total,
            "interest_shown": interest,
            "clicks": clicks,
            "conversions": conversions,
            "revenue": float(revenue),
            "conversion_rate": conversions / total if total > 0 else 0,
            "click_rate": clicks / total if total > 0 else 0,
        }

    @staticmethod
    async def get_top_products(
        db: AsyncSession,
        tenant_id: str,
        start_date: date,
        end_date: date,
        limit: int = 10,
    ) -> list[dict]:
        """Products ranked by conversion rate and revenue."""
        base_filter = and_(
            UpsellAttempt.tenant_id == tenant_id,
            func.date(UpsellAttempt.presented_at) >= start_date,
            func.date(UpsellAttempt.presented_at) <= end_date,
        )

        result = await db.execute(
            select(
                UpsellAttempt.product_id,
                Product.name,
                Product.category,
                Product.price,
                func.count(UpsellAttempt.id).label("attempts"),
                func.sum(
                    case(
                        (UpsellAttempt.outcome == UpsellOutcome.CONVERTED, 1),
                        else_=0,
                    )
                ).label("conversions"),
                func.coalesce(func.sum(UpsellAttempt.revenue_attributed), 0).label("revenue"),
            )
            .join(Product, Product.id == UpsellAttempt.product_id)
            .where(base_filter)
            .group_by(UpsellAttempt.product_id, Product.name, Product.category, Product.price)
            .order_by(func.sum(UpsellAttempt.revenue_attributed).desc())
            .limit(limit)
        )

        rows = result.all()
        return [
            {
                "product_id": str(row.product_id),
                "name": row.name,
                "category": row.category,
                "price": row.price,
                "attempts": row.attempts,
                "conversions": row.conversions,
                "revenue": float(row.revenue),
                "conversion_rate": row.conversions / row.attempts if row.attempts > 0 else 0,
            }
            for row in rows
        ]

    @staticmethod
    async def get_strategy_performance(
        db: AsyncSession,
        tenant_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Strategy performance including A/B test comparison."""
        base_filter = and_(
            UpsellAttempt.tenant_id == tenant_id,
            func.date(UpsellAttempt.presented_at) >= start_date,
            func.date(UpsellAttempt.presented_at) <= end_date,
            UpsellAttempt.strategy_id.isnot(None),
        )

        result = await db.execute(
            select(
                UpsellAttempt.strategy_id,
                UpsellStrategy.name,
                UpsellStrategy.trigger_type,
                UpsellAttempt.ab_test_group,
                func.count(UpsellAttempt.id).label("attempts"),
                func.sum(
                    case(
                        (UpsellAttempt.outcome == UpsellOutcome.CONVERTED, 1),
                        else_=0,
                    )
                ).label("conversions"),
                func.coalesce(func.sum(UpsellAttempt.revenue_attributed), 0).label("revenue"),
            )
            .join(UpsellStrategy, UpsellStrategy.id == UpsellAttempt.strategy_id)
            .where(base_filter)
            .group_by(
                UpsellAttempt.strategy_id,
                UpsellStrategy.name,
                UpsellStrategy.trigger_type,
                UpsellAttempt.ab_test_group,
            )
            .order_by(func.count(UpsellAttempt.id).desc())
        )

        rows = result.all()
        return [
            {
                "strategy_id": str(row.strategy_id),
                "name": row.name,
                "trigger_type": row.trigger_type.value if row.trigger_type else None,
                "ab_test_group": row.ab_test_group,
                "attempts": row.attempts,
                "conversions": row.conversions,
                "revenue": float(row.revenue),
                "conversion_rate": row.conversions / row.attempts if row.attempts > 0 else 0,
            }
            for row in rows
        ]

    @staticmethod
    async def get_revenue_attribution(
        db: AsyncSession,
        tenant_id: str,
        start_date: date,
        end_date: date,
    ) -> dict:
        """Total revenue attributed to bot conversations."""
        base_filter = and_(
            UpsellAttempt.tenant_id == tenant_id,
            func.date(UpsellAttempt.presented_at) >= start_date,
            func.date(UpsellAttempt.presented_at) <= end_date,
            UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
        )

        total_revenue = await db.scalar(
            select(func.coalesce(func.sum(UpsellAttempt.revenue_attributed), 0)).where(base_filter)
        ) or 0

        total_conversions = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(base_filter)
        ) or 0

        avg_revenue = total_revenue / total_conversions if total_conversions > 0 else 0

        return {
            "total_revenue": float(total_revenue),
            "total_conversions": total_conversions,
            "average_order_value": float(avg_revenue),
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        }

    @staticmethod
    async def get_cross_sell_patterns(
        db: AsyncSession,
        tenant_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Find products that frequently convert in the same conversations."""
        # Find conversations with 2+ converted attempts
        subq = (
            select(UpsellAttempt.conversation_id)
            .where(
                UpsellAttempt.tenant_id == tenant_id,
                UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
                UpsellAttempt.conversation_id.isnot(None),
            )
            .group_by(UpsellAttempt.conversation_id)
            .having(func.count(UpsellAttempt.id) >= 2)
            .subquery()
        )

        result = await db.execute(
            select(
                UpsellAttempt.product_id,
                Product.name,
                func.count(UpsellAttempt.id).label("co_conversions"),
            )
            .join(Product, Product.id == UpsellAttempt.product_id)
            .where(
                UpsellAttempt.conversation_id.in_(select(subq.c.conversation_id)),
                UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
            )
            .group_by(UpsellAttempt.product_id, Product.name)
            .order_by(func.count(UpsellAttempt.id).desc())
            .limit(limit)
        )

        rows = result.all()
        return [
            {
                "product_id": str(row.product_id),
                "name": row.name,
                "co_conversions": row.co_conversions,
            }
            for row in rows
        ]

    @staticmethod
    async def aggregate_daily_metrics(
        db: AsyncSession,
        tenant_id: str,
        target_date: date,
    ) -> SalesMetricDaily:
        """Run daily aggregation for the SalesMetricDaily table."""
        base_filter = and_(
            UpsellAttempt.tenant_id == tenant_id,
            func.date(UpsellAttempt.presented_at) == target_date,
        )

        total = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(base_filter)
        ) or 0
        interest = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter,
                UpsellAttempt.outcome.in_([
                    UpsellOutcome.INTEREST_SHOWN, UpsellOutcome.CLICKED, UpsellOutcome.CONVERTED
                ]),
            )
        ) or 0
        clicks = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter,
                UpsellAttempt.outcome.in_([UpsellOutcome.CLICKED, UpsellOutcome.CONVERTED]),
            )
        ) or 0
        conversions = await db.scalar(
            select(func.count(UpsellAttempt.id)).where(
                base_filter, UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
            )
        ) or 0
        revenue = await db.scalar(
            select(func.coalesce(func.sum(UpsellAttempt.revenue_attributed), 0)).where(
                base_filter, UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
            )
        ) or 0

        # Upsert the daily metric
        result = await db.execute(
            select(SalesMetricDaily).where(
                SalesMetricDaily.tenant_id == tenant_id,
                SalesMetricDaily.metric_date == target_date,
            )
        )
        metric = result.scalar_one_or_none()

        if not metric:
            metric = SalesMetricDaily(
                tenant_id=tenant_id,
                metric_date=target_date,
            )
            db.add(metric)

        metric.total_upsell_attempts = total
        metric.total_interest_shown = interest
        metric.total_clicks = clicks
        metric.total_conversions = conversions
        metric.total_revenue = float(revenue)
        metric.conversion_rate = conversions / total if total > 0 else 0
        await db.flush()

        return metric
