import logging
from typing import Optional
from datetime import date, datetime

import stripe
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.tenant import Tenant, PlanType
from app.models.usage import UsageRecord

logger = logging.getLogger(__name__)
settings = get_settings()

stripe.api_key = settings.stripe_secret_key

PLAN_PRICE_MAP = {
    PlanType.STARTER: settings.stripe_starter_price_id,
    PlanType.PROFESSIONAL: settings.stripe_professional_price_id,
    PlanType.ENTERPRISE: settings.stripe_enterprise_price_id,
}


class BillingService:
    """Stripe billing and usage metering."""

    @staticmethod
    async def create_customer(tenant: Tenant) -> str:
        """Create a Stripe customer for a tenant."""
        customer = stripe.Customer.create(
            name=tenant.name,
            metadata={"tenant_id": str(tenant.id), "plan": tenant.plan.value},
        )
        return customer.id

    @staticmethod
    async def create_subscription(
        customer_id: str,
        plan: PlanType,
    ) -> str:
        """Create a Stripe subscription."""
        price_id = PLAN_PRICE_MAP.get(plan)
        if not price_id:
            raise ValueError(f"No Stripe price configured for plan: {plan}")

        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete",
            expand=["latest_invoice.payment_intent"],
        )
        return subscription.id

    @staticmethod
    async def report_usage(
        subscription_id: str,
        quantity: int,
    ):
        """Report metered usage to Stripe for overage billing."""
        if not subscription_id:
            return

        subscription = stripe.Subscription.retrieve(subscription_id)
        for item in subscription["items"]["data"]:
            stripe.SubscriptionItem.create_usage_record(
                item.id,
                quantity=quantity,
                action="increment",
            )

    @staticmethod
    async def record_usage(
        db: AsyncSession,
        tenant_id: str,
        conversations: int = 0,
        messages: int = 0,
        tokens: int = 0,
    ):
        """Record daily usage in the database."""
        today = date.today()

        result = await db.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.record_date == today,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            record.conversation_count += conversations
            record.message_count += messages
            record.tokens_used += tokens
            # Rough cost estimate: $0.001 per 1K tokens
            record.estimated_cost += (tokens / 1000) * 0.001
        else:
            record = UsageRecord(
                tenant_id=tenant_id,
                record_date=today,
                conversation_count=conversations,
                message_count=messages,
                tokens_used=tokens,
                estimated_cost=(tokens / 1000) * 0.001,
            )
            db.add(record)

        await db.flush()

    @staticmethod
    async def get_monthly_usage(
        db: AsyncSession,
        tenant_id: str,
        year: int,
        month: int,
    ) -> dict:
        """Get aggregated usage for a specific month."""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        result = await db.execute(
            select(
                func.sum(UsageRecord.conversation_count).label("total_conversations"),
                func.sum(UsageRecord.message_count).label("total_messages"),
                func.sum(UsageRecord.tokens_used).label("total_tokens"),
                func.sum(UsageRecord.estimated_cost).label("total_cost"),
            ).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.record_date >= start_date,
                UsageRecord.record_date < end_date,
            )
        )
        row = result.one()

        return {
            "year": year,
            "month": month,
            "total_conversations": row.total_conversations or 0,
            "total_messages": row.total_messages or 0,
            "total_tokens": row.total_tokens or 0,
            "total_cost": round(row.total_cost or 0, 4),
        }

    @staticmethod
    async def get_daily_usage(
        db: AsyncSession,
        tenant_id: str,
        target_date: date,
    ) -> Optional[dict]:
        """Get usage for a specific day."""
        result = await db.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.record_date == target_date,
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return None

        return {
            "date": target_date.isoformat(),
            "conversation_count": record.conversation_count,
            "message_count": record.message_count,
            "tokens_used": record.tokens_used,
            "estimated_cost": round(record.estimated_cost, 4),
        }

    @staticmethod
    async def check_overage(
        db: AsyncSession,
        tenant: Tenant,
    ) -> dict:
        """Check if tenant has exceeded their plan's included conversations."""
        now = datetime.utcnow()
        usage = await BillingService.get_monthly_usage(
            db, str(tenant.id), now.year, now.month
        )
        limits = tenant.get_plan_limits()
        included = limits["monthly_conversations"]
        used = usage["total_conversations"]
        overage = max(0, used - included)

        return {
            "included": included,
            "used": used,
            "remaining": max(0, included - used),
            "overage": overage,
            "overage_cost": round(overage * limits["overage_rate"], 2),
        }
