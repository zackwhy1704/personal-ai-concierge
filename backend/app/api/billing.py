"""
Stripe billing API — webhook handler + subscription management.

Handles these Stripe events:
- checkout.session.completed        → new subscription activated
- invoice.payment_succeeded         → recurring payment success
- invoice.payment_failed            → payment failed (retry or suspend)
- customer.subscription.updated     → plan change, renewal
- customer.subscription.deleted     → cancellation
- customer.subscription.paused      → subscription paused
- customer.subscription.resumed     → subscription resumed
- charge.dispute.created            → chargeback/dispute opened
- charge.refunded                   → refund processed
"""
import logging
from datetime import datetime
from typing import Optional

import stripe
from stripe.error import SignatureVerificationError as StripeSignatureError
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db, async_session_factory
from app.models.tenant import Tenant, PlanType, TenantStatus
from app.api.auth import get_current_tenant
from app.services.whatsapp import WhatsAppService
from app.pricing import (
    get_currency_symbol,
    get_plan_price,
    get_plan_price_formatted,
    get_plan_prices_dict,
    get_stripe_price_id,
    get_all_price_to_plan,
    get_plans_for_currency,
    SUPPORTED_CURRENCIES,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/billing", tags=["billing"])

stripe.api_key = settings.stripe_secret_key


def _get_price_to_plan() -> dict:
    """Reverse map: price_id -> PlanType across all currencies."""
    return get_all_price_to_plan()

whatsapp = WhatsAppService()


# ──────────────────────────────────────────────
# Stripe Checkout — create a payment session
# ──────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # "starter", "professional", "enterprise"
    success_url: str = "https://concierge.yourdomain.com/dashboard?payment=success"
    cancel_url: str = "https://concierge.yourdomain.com/dashboard?payment=cancelled"


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    data: CheckoutRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for subscription."""
    try:
        plan = PlanType(data.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {data.plan}")
    price_id = get_stripe_price_id(tenant.currency, data.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"No Stripe price configured for {tenant.currency} {data.plan}")

    # Create or reuse Stripe customer
    if not tenant.stripe_customer_id:
        customer = stripe.Customer.create(
            name=tenant.name,
            metadata={"tenant_id": str(tenant.id)},
        )
        tenant.stripe_customer_id = customer.id
        await db.flush()

    session = stripe.checkout.Session.create(
        customer=tenant.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=data.success_url,
        cancel_url=data.cancel_url,
        allow_promotion_codes=True,
        metadata={"tenant_id": str(tenant.id), "plan": plan.value},
        subscription_data={
            "metadata": {"tenant_id": str(tenant.id), "plan": plan.value},
        },
    )

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


# ──────────────────────────────────────────────
# Subscription status
# ──────────────────────────────────────────────

class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    plan: str
    status: str  # active, past_due, canceled, paused, trialing, unpaid
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False
    trial_end: Optional[str] = None
    stripe_customer_id: Optional[str] = None


@router.get("/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get current subscription status from Stripe."""
    if not tenant.stripe_subscription_id:
        return SubscriptionStatusResponse(
            has_subscription=False,
            plan=tenant.plan.value,
            status="none",
            stripe_customer_id=tenant.stripe_customer_id,
        )

    try:
        sub = stripe.Subscription.retrieve(tenant.stripe_subscription_id)
        trial_end = None
        if sub.trial_end:
            trial_end = datetime.fromtimestamp(sub.trial_end).isoformat()
        return SubscriptionStatusResponse(
            has_subscription=True,
            plan=tenant.plan.value,
            status=sub.status,
            current_period_end=datetime.fromtimestamp(sub.current_period_end).isoformat(),
            cancel_at_period_end=sub.cancel_at_period_end,
            trial_end=trial_end,
            stripe_customer_id=tenant.stripe_customer_id,
        )
    except stripe.error.InvalidRequestError:
        return SubscriptionStatusResponse(
            has_subscription=False,
            plan=tenant.plan.value,
            status="invalid",
            stripe_customer_id=tenant.stripe_customer_id,
        )


@router.post("/cancel")
async def cancel_subscription(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Cancel subscription at end of billing period."""
    if not tenant.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    sub = stripe.Subscription.modify(
        tenant.stripe_subscription_id,
        cancel_at_period_end=True,
    )

    return {
        "status": "cancelling",
        "cancel_at": datetime.fromtimestamp(sub.current_period_end).isoformat(),
        "message": "Subscription will be cancelled at the end of the current billing period",
    }


@router.post("/reactivate")
async def reactivate_subscription(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Reactivate a subscription that was set to cancel."""
    if not tenant.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    stripe.Subscription.modify(
        tenant.stripe_subscription_id,
        cancel_at_period_end=False,
    )

    return {"status": "active", "message": "Subscription reactivated"}


# ──────────────────────────────────────────────
# Stripe Webhook — handles ALL payment events
# ──────────────────────────────────────────────

@router.post("/webhook/stripe")
async def handle_stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify webhook signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except StripeSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    logger.info(f"Stripe webhook received: {event_type}")

    handlers = {
        "checkout.session.completed": _handle_checkout_completed,
        "invoice.payment_succeeded": _handle_payment_succeeded,
        "invoice.payment_failed": _handle_payment_failed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "customer.subscription.paused": _handle_subscription_paused,
        "customer.subscription.resumed": _handle_subscription_resumed,
        "charge.dispute.created": _handle_dispute_created,
        "charge.refunded": _handle_refund,
    }

    handler = handlers.get(event_type)
    if handler:
        try:
            await handler(data)
        except Exception:
            logger.exception(f"Error handling Stripe event: {event_type}")
            # Return 200 to avoid Stripe retries for our errors
            # Log for manual investigation

    return {"status": "ok"}


# ──────────────────────────────────────────────
# Event Handlers
# ──────────────────────────────────────────────

async def _handle_checkout_completed(session: dict):
    """New subscription created via Checkout."""
    tenant_id = session.get("metadata", {}).get("tenant_id")
    subscription_id = session.get("subscription")
    customer_id = session.get("customer")
    plan_str = session.get("metadata", {}).get("plan", "starter")

    if not tenant_id:
        logger.error("Checkout completed but no tenant_id in metadata")
        return

    async with async_session_factory() as db:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            logger.error(f"Tenant not found: {tenant_id}")
            return

        tenant.stripe_customer_id = customer_id
        tenant.stripe_subscription_id = subscription_id
        tenant.plan = PlanType(plan_str)
        tenant.status = TenantStatus.ACTIVE
        tenant.updated_at = datetime.utcnow()

        await db.commit()

        # Check if this is a promo/trial subscription
        is_trial = False
        trial_end_date = ""
        discount_code = None
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                # Detect trial from Stripe coupon applied via promotion code
                if sub.discount and sub.discount.coupon:
                    discount_code = sub.discount.promotion_code
                    is_trial = True
                    # Use current_period_end as the "free" period end
                    if sub.current_period_end:
                        trial_end_date = datetime.fromtimestamp(sub.current_period_end).strftime("%B %d, %Y")
                # Also detect native Stripe trial
                if sub.status == "trialing" and sub.trial_end:
                    is_trial = True
                    trial_end_date = datetime.fromtimestamp(sub.trial_end).strftime("%B %d, %Y")
            except Exception:
                pass

        # Track promo redemption in our DB
        if discount_code:
            try:
                from app.models.promo_code import PromoCode
                promo_result = await db.execute(
                    select(PromoCode).where(PromoCode.stripe_promo_id == discount_code)
                )
                promo = promo_result.scalar_one_or_none()
                if promo:
                    promo.times_redeemed += 1
                    await db.commit()
            except Exception:
                pass

        # Notify admin via WhatsApp
        sym = get_currency_symbol(tenant.currency)
        plan_price = get_plan_price(tenant.currency, plan_str)
        if is_trial:
            await _notify_admin(
                tenant,
                f"Free trial activated! Your {plan_str.title()} plan "
                f"({sym}{plan_price:,}/mo) is now active.\n\n"
                f"First month free — trial ends: {trial_end_date}\n"
                f"Your card will be charged after the trial.\n"
                f"You're all set to start using AI Concierge!",
            )
        else:
            await _notify_admin(
                tenant,
                f"Payment successful! Your {plan_str.title()} plan "
                f"({sym}{plan_price:,}/mo) is now active.\n\n"
                f"Subscription ID: {subscription_id}\n"
                f"You're all set to start using AI Concierge!",
            )

    logger.info(f"Checkout completed for tenant {tenant_id}, plan={plan_str}")


async def _handle_payment_succeeded(invoice: dict):
    """Recurring payment succeeded."""
    subscription_id = invoice.get("subscription")
    customer_id = invoice.get("customer")
    amount_paid = invoice.get("amount_paid", 0) / 100  # cents to dollars
    period_end = invoice.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")

    if not subscription_id:
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            # Try by customer_id
            result = await db.execute(
                select(Tenant).where(Tenant.stripe_customer_id == customer_id)
            )
            tenant = result.scalar_one_or_none()

        if not tenant:
            logger.warning(f"No tenant found for subscription: {subscription_id}")
            return

        # Ensure tenant is active
        if tenant.status != TenantStatus.ACTIVE:
            tenant.status = TenantStatus.ACTIVE
            tenant.updated_at = datetime.utcnow()
            await db.commit()

        # Notify admin
        next_date = ""
        if period_end:
            next_date = datetime.fromtimestamp(period_end).strftime("%B %d, %Y")

        sym = get_currency_symbol(tenant.currency)
        await _notify_admin(
            tenant,
            f"Payment received: {sym}{amount_paid:.2f}\n"
            f"Plan: {tenant.plan.value.title()}\n"
            f"Next billing date: {next_date}\n"
            f"Thank you for your continued subscription!",
        )

    logger.info(f"Payment succeeded for subscription {subscription_id}: ${amount_paid}")


async def _handle_payment_failed(invoice: dict):
    """Payment failed — Stripe will retry automatically (up to 3 times)."""
    subscription_id = invoice.get("subscription")
    attempt_count = invoice.get("attempt_count", 0)
    next_attempt = invoice.get("next_payment_attempt")
    amount_due = invoice.get("amount_due", 0) / 100

    if not subscription_id:
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        # After 3 failed attempts, suspend the tenant
        if attempt_count >= 3:
            tenant.status = TenantStatus.SUSPENDED
            tenant.updated_at = datetime.utcnow()
            await db.commit()

            sym = get_currency_symbol(tenant.currency)
            await _notify_admin(
                tenant,
                f"URGENT: Your account has been suspended due to repeated payment failures.\n\n"
                f"Amount due: {sym}{amount_due:.2f}\n"
                f"Failed attempts: {attempt_count}\n\n"
                f"Please update your payment method at the dashboard to restore service.\n"
                f"Your chatbot will stop responding to guests until payment is resolved.",
            )
        else:
            next_retry = ""
            if next_attempt:
                next_retry = datetime.fromtimestamp(next_attempt).strftime("%B %d at %I:%M %p")

            sym = get_currency_symbol(tenant.currency)
            await _notify_admin(
                tenant,
                f"Payment failed (attempt {attempt_count}/3)\n\n"
                f"Amount: {sym}{amount_due:.2f}\n"
                f"Next retry: {next_retry}\n\n"
                f"Please ensure your payment method is up to date in the dashboard.",
            )

    logger.warning(f"Payment failed for subscription {subscription_id}, attempt {attempt_count}")


async def _handle_subscription_updated(subscription: dict):
    """Subscription updated — plan change, renewal, or status change."""
    subscription_id = subscription.get("id")
    status = subscription.get("status")  # active, past_due, unpaid, canceled
    cancel_at_period_end = subscription.get("cancel_at_period_end", False)

    if not subscription_id:
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        # Detect plan change
        items = subscription.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
            price_plan_map = _get_price_to_plan()
            new_plan = price_plan_map.get(price_id)
            if new_plan and new_plan != tenant.plan:
                old_plan = tenant.plan
                tenant.plan = new_plan
                tenant.updated_at = datetime.utcnow()
                await db.commit()

                await _notify_admin(
                    tenant,
                    f"Plan changed: {old_plan.value.title()} -> {new_plan.value.title()}\n"
                    f"New monthly rate: {get_plan_price_formatted(tenant.currency, new_plan.value)}/mo\n"
                    f"Changes take effect immediately.",
                )
                return

        # Handle status changes
        if status == "past_due":
            await _notify_admin(
                tenant,
                "Your subscription is past due. Please update your payment method.\n"
                "Service will continue temporarily, but may be suspended if not resolved.",
            )
        elif status == "active" and not cancel_at_period_end:
            # Subscription renewed or reactivated
            period_end = subscription.get("current_period_end")
            next_date = ""
            if period_end:
                next_date = datetime.fromtimestamp(period_end).strftime("%B %d, %Y")

            await _notify_admin(
                tenant,
                f"Subscription renewed successfully!\n"
                f"Plan: {tenant.plan.value.title()}\n"
                f"Next billing: {next_date}",
            )

        if cancel_at_period_end:
            cancel_at = subscription.get("current_period_end")
            cancel_date = ""
            if cancel_at:
                cancel_date = datetime.fromtimestamp(cancel_at).strftime("%B %d, %Y")
            await _notify_admin(
                tenant,
                f"Subscription set to cancel on {cancel_date}.\n"
                f"You can reactivate anytime before then from the dashboard.\n"
                f"Service continues until the end of your billing period.",
            )

        tenant.updated_at = datetime.utcnow()
        await db.commit()

    logger.info(f"Subscription updated: {subscription_id}, status={status}")


async def _handle_subscription_deleted(subscription: dict):
    """Subscription fully cancelled (end of period reached or immediate cancel)."""
    subscription_id = subscription.get("id")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        tenant.status = TenantStatus.SUSPENDED
        tenant.stripe_subscription_id = None
        tenant.updated_at = datetime.utcnow()
        await db.commit()

        await _notify_admin(
            tenant,
            "Your subscription has been cancelled.\n\n"
            "Your AI concierge chatbot is now offline and will stop responding to guests.\n"
            "All your data (knowledge base, guardrails, intents) is preserved.\n\n"
            "To reactivate, visit the dashboard and subscribe to a new plan.",
        )

    logger.info(f"Subscription deleted: {subscription_id}")


async def _handle_subscription_paused(subscription: dict):
    """Subscription paused (if pause collection is enabled)."""
    subscription_id = subscription.get("id")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        tenant.status = TenantStatus.SUSPENDED
        tenant.updated_at = datetime.utcnow()
        await db.commit()

        await _notify_admin(
            tenant,
            "Your subscription has been paused.\n"
            "Your chatbot is temporarily offline.\n"
            "Resume your subscription from the dashboard when ready.",
        )

    logger.info(f"Subscription paused: {subscription_id}")


async def _handle_subscription_resumed(subscription: dict):
    """Subscription resumed from pause."""
    subscription_id = subscription.get("id")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        tenant.status = TenantStatus.ACTIVE
        tenant.updated_at = datetime.utcnow()
        await db.commit()

        await _notify_admin(
            tenant,
            "Your subscription has been resumed!\n"
            "Your AI concierge chatbot is back online and ready to serve guests.",
        )

    logger.info(f"Subscription resumed: {subscription_id}")


async def _handle_dispute_created(dispute: dict):
    """Chargeback or dispute opened — alert immediately."""
    charge_id = dispute.get("charge")
    amount = dispute.get("amount", 0) / 100
    reason = dispute.get("reason", "unknown")

    # Find tenant by charge → invoice → subscription
    if not charge_id:
        return

    try:
        charge = stripe.Charge.retrieve(charge_id)
        customer_id = charge.get("customer")
    except Exception:
        logger.error(f"Could not retrieve charge: {charge_id}")
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_customer_id == customer_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        # Suspend on dispute
        tenant.status = TenantStatus.SUSPENDED
        tenant.updated_at = datetime.utcnow()
        await db.commit()

        sym = get_currency_symbol(tenant.currency)
        await _notify_admin(
            tenant,
            f"URGENT: A payment dispute has been filed.\n\n"
            f"Amount: {sym}{amount:.2f}\n"
            f"Reason: {reason}\n\n"
            f"Your account has been suspended pending resolution.\n"
            f"Please contact support immediately.",
        )

    logger.warning(f"Dispute created for customer {customer_id}: ${amount}, reason={reason}")


async def _handle_refund(charge: dict):
    """Refund processed."""
    customer_id = charge.get("customer")
    amount_refunded = charge.get("amount_refunded", 0) / 100

    if not customer_id:
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Tenant).where(Tenant.stripe_customer_id == customer_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return

        sym = get_currency_symbol(tenant.currency)
        await _notify_admin(
            tenant,
            f"A refund of {sym}{amount_refunded:.2f} has been processed to your account.\n"
            f"Please allow 5-10 business days for the refund to appear.",
        )

    logger.info(f"Refund processed for customer {customer_id}: ${amount_refunded}")


# ──────────────────────────────────────────────
# Pricing endpoint
# ──────────────────────────────────────────────

@router.get("/pricing")
async def get_pricing(currency: str = "MYR"):
    """Return plan pricing for a given currency."""
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}. Supported: {', '.join(SUPPORTED_CURRENCIES)}")

    return {
        "currency": currency,
        "symbol": get_currency_symbol(currency),
        "plans": get_plans_for_currency(currency),
    }


# ──────────────────────────────────────────────
# WhatsApp notification helper
# ──────────────────────────────────────────────

async def _notify_admin(tenant: Tenant, message: str):
    """Send a notification to all admin phone numbers via WhatsApp."""
    if not tenant.whatsapp_phone_number_id or not tenant.whatsapp_access_token:
        logger.warning(f"Cannot notify tenant {tenant.id}: no WhatsApp config")
        return

    admin_phones = tenant.get_admin_phones()
    if not admin_phones:
        logger.warning(f"Cannot notify tenant {tenant.id}: no admin phones")
        return

    prefix = f"[{tenant.name}] Billing Alert\n{'─' * 25}\n"
    full_message = prefix + message

    for phone in admin_phones:
        try:
            await whatsapp.send_text_message(
                tenant.whatsapp_phone_number_id,
                tenant.whatsapp_access_token,
                phone,
                full_message,
            )
        except Exception:
            logger.exception(f"Failed to send WhatsApp notification to {phone}")
