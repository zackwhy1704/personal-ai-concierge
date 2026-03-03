"""
End-to-end payment flow tests.

Tests simulate complete user journeys:
1. Onboarding → Checkout → Payment Success → Active tenant
2. Active tenant → Payment Failed → Retry → Suspended
3. Suspended → New Payment → Reactivated
4. Active → Cancel at period end → Subscription deleted → Suspended
5. Active → Dispute → Suspended → Refund
6. Active → Plan upgrade → Correct notifications
7. Active → Pause → Resume → Active
8. Token lifecycle: create → expire → refresh → use
"""
import json
import uuid
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import jwt as pyjwt

from app.api.auth import create_jwt_token
from app.config import get_settings
from app.models.tenant import PlanType, TenantStatus

settings = get_settings()


def _event(event_type: str, data: dict) -> dict:
    return {"id": f"evt_{uuid.uuid4().hex[:12]}", "type": event_type, "data": {"object": data}}


def _mock_db_session(tenant):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = tenant
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session


async def _send_webhook(client, event):
    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(event.get("_tenant"))

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )
        return response, mock_notify


# ──────────────────────────────────────────────
# E2E Flow 1: Onboarding → Checkout → Active
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_onboarding_to_active(client, test_tenant):
    """Full flow: create checkout → payment succeeds → tenant activated."""
    # Step 1: Tenant starts in ONBOARDING
    test_tenant.status = TenantStatus.ONBOARDING
    test_tenant.stripe_customer_id = None
    test_tenant.stripe_subscription_id = None

    # Step 2: Create checkout session
    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.settings") as mock_settings:
        mock_settings.stripe_starter_price_id = "price_starter"
        mock_settings.stripe_professional_price_id = "price_professional"
        mock_settings.stripe_enterprise_price_id = "price_enterprise"
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_e2e")
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/e2e", id="cs_e2e"
        )

        response = await client.post("/api/billing/checkout", json={
            "plan": "professional",
            "success_url": "https://example.com/ok",
            "cancel_url": "https://example.com/cancel",
        })
        assert response.status_code == 200
        assert response.json()["checkout_url"] == "https://checkout.stripe.com/e2e"

    # Step 3: Stripe sends checkout.session.completed webhook
    checkout_event = _event("checkout.session.completed", {
        "id": "cs_e2e",
        "customer": "cus_new_e2e",
        "subscription": "sub_e2e_123",
        "metadata": {"tenant_id": str(test_tenant.id), "plan": "professional"},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = checkout_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(checkout_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200

    # Verify final state
    assert test_tenant.status == TenantStatus.ACTIVE
    assert test_tenant.plan == PlanType.PROFESSIONAL
    assert test_tenant.stripe_customer_id == "cus_new_e2e"
    assert test_tenant.stripe_subscription_id == "sub_e2e_123"


# ──────────────────────────────────────────────
# E2E Flow 2: Payment Failures → Suspension
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_payment_failures_to_suspension(client, test_tenant):
    """Full flow: 1st failure → 2nd failure → 3rd failure = suspended."""
    test_tenant.status = TenantStatus.ACTIVE
    test_tenant.stripe_subscription_id = "sub_e2e_123"

    for attempt, should_suspend in [(1, False), (2, False), (3, True)]:
        event = _event("invoice.payment_failed", {
            "id": f"in_fail_{attempt}",
            "subscription": "sub_e2e_123",
            "customer": "cus_test",
            "amount_paid": 0,
            "amount_due": 280000,
            "attempt_count": attempt,
            "next_payment_attempt": int(datetime(2026, 4, 5).timestamp()) if attempt < 3 else None,
            "lines": {"data": [{"period": {"end": int(datetime(2026, 4, 1).timestamp())}}]},
        })

        with patch("app.api.billing.stripe") as mock_stripe, \
             patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
             patch("app.api.billing.async_session_factory") as mock_sf:

            mock_stripe.Webhook.construct_event.return_value = event
            mock_sf.return_value = _mock_db_session(test_tenant)

            response = await client.post(
                "/api/billing/webhook/stripe",
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )
            assert response.status_code == 200

            msg = mock_notify.call_args[0][1]
            if should_suspend:
                assert test_tenant.status == TenantStatus.SUSPENDED
                assert "URGENT" in msg
                assert "suspended" in msg
            else:
                assert test_tenant.status == TenantStatus.ACTIVE
                assert f"attempt {attempt}/3" in msg


# ──────────────────────────────────────────────
# E2E Flow 3: Suspended → Payment → Reactivated
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_suspended_to_reactivated(client, test_tenant):
    """Suspended tenant is reactivated after successful payment."""
    test_tenant.status = TenantStatus.SUSPENDED
    test_tenant.stripe_subscription_id = "sub_e2e_123"

    event = _event("invoice.payment_succeeded", {
        "id": "in_reactivate",
        "subscription": "sub_e2e_123",
        "customer": "cus_test",
        "amount_paid": 280000,
        "amount_due": 280000,
        "attempt_count": 1,
        "lines": {"data": [{"period": {"end": int(datetime(2026, 5, 1).timestamp())}}]},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200

    assert test_tenant.status == TenantStatus.ACTIVE


# ──────────────────────────────────────────────
# E2E Flow 4: Cancel → Period End → Deleted
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_cancel_to_deletion(client, test_tenant):
    """Active → cancel at period end → subscription deleted → suspended."""
    test_tenant.status = TenantStatus.ACTIVE
    test_tenant.stripe_subscription_id = "sub_e2e_123"

    # Step 1: User cancels (API endpoint)
    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.modify.return_value = MagicMock(
            current_period_end=int(datetime(2026, 4, 1).timestamp())
        )
        response = await client.post("/api/billing/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelling"

    # Step 2: Stripe sends subscription.updated with cancel_at_period_end
    update_event = _event("customer.subscription.updated", {
        "id": "sub_e2e_123",
        "status": "active",
        "cancel_at_period_end": True,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": [{"price": {"id": "price_professional"}}]},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = update_event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {"price_professional": PlanType.PROFESSIONAL}

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(update_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "cancel" in msg.lower()

    # Step 3: Period ends, Stripe sends subscription.deleted
    delete_event = _event("customer.subscription.deleted", {
        "id": "sub_e2e_123",
        "status": "canceled",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": []},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = delete_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(delete_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200

    assert test_tenant.status == TenantStatus.SUSPENDED
    assert test_tenant.stripe_subscription_id is None


# ──────────────────────────────────────────────
# E2E Flow 5: Dispute → Suspended → Refund
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_dispute_to_refund(client, test_tenant):
    """Dispute suspends tenant, then refund is processed."""
    test_tenant.status = TenantStatus.ACTIVE
    test_tenant.stripe_customer_id = "cus_e2e_123"

    # Step 1: Dispute
    dispute_event = _event("charge.dispute.created", {
        "charge": "ch_e2e", "amount": 280000, "reason": "product_not_received"
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = dispute_event
        mock_stripe.Charge.retrieve.return_value = {"customer": "cus_e2e_123"}
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(dispute_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200

    assert test_tenant.status == TenantStatus.SUSPENDED

    # Step 2: Refund
    refund_event = _event("charge.refunded", {
        "customer": "cus_e2e_123", "amount_refunded": 280000
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = refund_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(refund_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "RM2800.00" in msg
        assert "refund" in msg.lower()


# ──────────────────────────────────────────────
# E2E Flow 6: Plan Upgrade
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_plan_upgrade_starter_to_enterprise(client, test_tenant):
    """Upgrade from starter → enterprise via subscription update."""
    test_tenant.status = TenantStatus.ACTIVE
    test_tenant.plan = PlanType.STARTER
    test_tenant.stripe_subscription_id = "sub_e2e_123"

    event = _event("customer.subscription.updated", {
        "id": "sub_e2e_123",
        "status": "active",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": [{"price": {"id": "price_enterprise"}}]},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {"price_enterprise": PlanType.ENTERPRISE}

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200

    assert test_tenant.plan == PlanType.ENTERPRISE
    msg = mock_notify.call_args[0][1]
    assert "Starter" in msg
    assert "Enterprise" in msg
    assert "RM6800" in msg


# ──────────────────────────────────────────────
# E2E Flow 7: Pause → Resume
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_pause_resume_cycle(client, test_tenant):
    """Active → paused → resumed → active."""
    test_tenant.status = TenantStatus.ACTIVE
    test_tenant.stripe_subscription_id = "sub_e2e_123"

    # Pause
    pause_event = _event("customer.subscription.paused", {
        "id": "sub_e2e_123", "status": "paused",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": []},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = pause_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(pause_event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.status == TenantStatus.SUSPENDED

    # Resume
    resume_event = _event("customer.subscription.resumed", {
        "id": "sub_e2e_123", "status": "active",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": []},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = resume_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(resume_event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.status == TenantStatus.ACTIVE


# ──────────────────────────────────────────────
# E2E Flow 8: Token Lifecycle
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_token_lifecycle(client, test_tenant):
    """Create token → use it → let it expire → refresh → use new token."""
    # Step 1: Create a token
    token = create_jwt_token(str(test_tenant.id))

    # Step 2: Use token successfully (check endpoint)
    response = await client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True

    # Step 3: Create an expired token (simulate passage of time)
    expired_payload = {
        "sub": str(test_tenant.id),
        "exp": datetime.utcnow() - timedelta(minutes=30),
        "iat": datetime.utcnow() - timedelta(hours=24, minutes=30),
    }
    expired_token = pyjwt.encode(expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    # Step 4: Expired token fails on check
    response = await client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401

    # Step 5: But can be refreshed
    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 200
    new_token = response.json()["token"]

    # Step 6: New token works
    response = await client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


# ──────────────────────────────────────────────
# E2E Flow 9: Full Payment Lifecycle
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_full_payment_lifecycle(client, test_tenant):
    """Complete lifecycle: subscribe → pay → upgrade → cancel → delete."""
    test_tenant.status = TenantStatus.ONBOARDING

    # 1. Checkout completed → Active
    event = _event("checkout.session.completed", {
        "id": "cs_lifecycle",
        "customer": "cus_lifecycle",
        "subscription": "sub_lifecycle",
        "metadata": {"tenant_id": str(test_tenant.id), "plan": "starter"},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.status == TenantStatus.ACTIVE
    assert test_tenant.plan == PlanType.STARTER

    # 2. Monthly payment succeeds
    pay_event = _event("invoice.payment_succeeded", {
        "id": "in_month1",
        "subscription": "sub_lifecycle",
        "customer": "cus_lifecycle",
        "amount_paid": 78000,
        "amount_due": 78000,
        "attempt_count": 1,
        "lines": {"data": [{"period": {"end": int(datetime(2026, 5, 1).timestamp())}}]},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = pay_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(pay_event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.status == TenantStatus.ACTIVE

    # 3. Upgrade to Professional
    upgrade_event = _event("customer.subscription.updated", {
        "id": "sub_lifecycle",
        "status": "active",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 5, 1).timestamp()),
        "items": {"data": [{"price": {"id": "price_pro"}}]},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = upgrade_event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {"price_pro": PlanType.PROFESSIONAL}

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(upgrade_event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.plan == PlanType.PROFESSIONAL

    # 4. Cancel at period end
    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.modify.return_value = MagicMock(
            current_period_end=int(datetime(2026, 5, 1).timestamp())
        )
        response = await client.post("/api/billing/cancel")
        assert response.status_code == 200

    # 5. Subscription deleted
    delete_event = _event("customer.subscription.deleted", {
        "id": "sub_lifecycle",
        "status": "canceled",
        "cancel_at_period_end": False,
        "current_period_end": int(datetime(2026, 5, 1).timestamp()),
        "items": {"data": []},
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = delete_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(delete_event).encode(),
            headers={"stripe-signature": "valid"},
        )

    assert test_tenant.status == TenantStatus.SUSPENDED
    assert test_tenant.stripe_subscription_id is None
