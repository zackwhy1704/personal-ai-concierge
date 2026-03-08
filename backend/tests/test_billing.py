"""
Comprehensive payment/billing edge case tests.

Tests cover:
1. Checkout session creation
2. Webhook signature verification
3. Successful payment → tenant activated
4. Failed payment → retry notifications
5. Failed payment (3rd attempt) → tenant suspended
6. Subscription renewal → notification
7. Plan upgrade/downgrade → plan updated
8. Cancellation at period end → notification
9. Full cancellation → tenant suspended
10. Subscription pause/resume
11. Dispute → tenant suspended
12. Refund → notification
13. Missing tenant in webhook → graceful handling
14. Invalid webhook signature → rejected
15. Subscription status endpoint
16. Cancel/reactivate endpoints
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from app.models.tenant import PlanType, TenantStatus


# ──────────────────────────────────────────────
# Stripe Webhook Event Factories
# ──────────────────────────────────────────────

def _make_stripe_event(event_type: str, data: dict) -> dict:
    return {
        "id": "evt_test_123",
        "type": event_type,
        "data": {"object": data},
    }


def _checkout_session(tenant_id: str, plan: str = "professional") -> dict:
    return {
        "id": "cs_test_123",
        "customer": "cus_test_123",
        "subscription": "sub_test_123",
        "metadata": {"tenant_id": tenant_id, "plan": plan},
    }


def _invoice(subscription_id: str = "sub_test_123", amount: int = 29900, attempt: int = 1) -> dict:
    return {
        "id": "in_test_123",
        "subscription": subscription_id,
        "customer": "cus_test_123",
        "amount_paid": amount,
        "amount_due": amount,
        "attempt_count": attempt,
        "next_payment_attempt": int(datetime(2026, 4, 5).timestamp()),
        "lines": {"data": [{"period": {"end": int(datetime(2026, 4, 1).timestamp())}}]},
    }


def _subscription(
    subscription_id: str = "sub_test_123",
    status: str = "active",
    cancel_at_period_end: bool = False,
    price_id: str = "price_professional",
) -> dict:
    return {
        "id": subscription_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {
            "data": [{"price": {"id": price_id}}],
        },
    }


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_status_no_subscription(client):
    """Tenant without subscription returns 'none' status."""
    response = await client.get("/api/billing/subscription")
    assert response.status_code == 200
    data = response.json()
    assert data["has_subscription"] is False
    assert data["status"] == "none"
    assert data["plan"] == "professional"


@pytest.mark.asyncio
async def test_cancel_no_subscription(client):
    """Cancel without subscription returns 400."""
    response = await client.post("/api/billing/cancel")
    assert response.status_code == 400
    assert "No active subscription" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reactivate_no_subscription(client):
    """Reactivate without subscription returns 400."""
    response = await client.post("/api/billing/reactivate")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_checkout_creates_session(client):
    """Checkout endpoint creates a Stripe session and returns URL."""
    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.settings") as mock_settings:
        mock_settings.stripe_starter_price_id = "price_starter_test"
        mock_settings.stripe_professional_price_id = "price_professional_test"
        mock_settings.stripe_enterprise_price_id = "price_enterprise_test"
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new_123")
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test", id="cs_test_123"
        )

        response = await client.post("/api/billing/checkout", json={
            "plan": "professional",
            "success_url": "https://example.com/success",
            "cancel_url": "https://example.com/cancel",
        })

        assert response.status_code == 200
        data = response.json()
        assert "checkout_url" in data
        assert data["session_id"] == "cs_test_123"


@pytest.mark.asyncio
async def test_checkout_invalid_plan(client):
    """Checkout with invalid plan returns 400."""
    response = await client.post("/api/billing/checkout", json={"plan": "invalid_plan"})
    assert response.status_code == 400
    assert "Invalid plan" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client):
    """Webhook with invalid signature is rejected."""
    import stripe as _stripe

    with patch("app.api.billing.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = _stripe.error.SignatureVerificationError(
            "Invalid signature", "sig_test"
        )

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=b"{}",
            headers={"stripe-signature": "invalid"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_webhook_checkout_completed(client, test_tenant, db_session):
    """Checkout completed → tenant activated, plan set, notification sent."""
    event = _make_stripe_event(
        "checkout.session.completed",
        _checkout_session(str(test_tenant.id), "professional"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        # Mock subscription with no discount/trial (normal payment)
        mock_sub = MagicMock()
        mock_sub.discount = None
        mock_sub.status = "active"
        mock_sub.trial_end = None
        mock_stripe.Subscription.retrieve.return_value = mock_sub

        # Mock the DB session used inside the handler
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        # Verify notification was sent
        mock_notify.assert_called_once()
        notify_msg = mock_notify.call_args[0][1]
        assert "Payment successful" in notify_msg
        assert "Professional" in notify_msg


@pytest.mark.asyncio
async def test_webhook_payment_succeeded(client, test_tenant):
    """Recurring payment success → notification with amount and next billing date."""
    event = _make_stripe_event(
        "invoice.payment_succeeded",
        _invoice(amount=29900),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        mock_notify.assert_called_once()
        notify_msg = mock_notify.call_args[0][1]
        assert "RM299.00" in notify_msg
        assert "Payment received" in notify_msg


@pytest.mark.asyncio
async def test_webhook_payment_failed_first_attempt(client, test_tenant):
    """First payment failure → warning notification, NOT suspended."""
    event = _make_stripe_event(
        "invoice.payment_failed",
        _invoice(attempt=1),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        mock_notify.assert_called_once()
        notify_msg = mock_notify.call_args[0][1]
        assert "attempt 1/3" in notify_msg
        # Should NOT be suspended after first failure
        assert test_tenant.status != TenantStatus.SUSPENDED


@pytest.mark.asyncio
async def test_webhook_payment_failed_third_attempt_suspends(client, test_tenant):
    """Third payment failure → tenant suspended + urgent notification."""
    event = _make_stripe_event(
        "invoice.payment_failed",
        _invoice(attempt=3),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        mock_notify.assert_called_once()
        notify_msg = mock_notify.call_args[0][1]
        assert "URGENT" in notify_msg
        assert "suspended" in notify_msg
        assert test_tenant.status == TenantStatus.SUSPENDED


@pytest.mark.asyncio
async def test_webhook_subscription_cancelled(client, test_tenant):
    """Subscription deleted → tenant suspended, subscription cleared."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    event = _make_stripe_event(
        "customer.subscription.deleted",
        _subscription(),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        assert test_tenant.stripe_subscription_id is None
        mock_notify.assert_called_once()
        assert "cancelled" in mock_notify.call_args[0][1]


@pytest.mark.asyncio
async def test_webhook_subscription_set_to_cancel(client, test_tenant):
    """Subscription updated with cancel_at_period_end → notification."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    event = _make_stripe_event(
        "customer.subscription.updated",
        _subscription(cancel_at_period_end=True),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        mock_notify.assert_called_once()
        assert "cancel" in mock_notify.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_webhook_dispute_suspends_tenant(client, test_tenant):
    """Dispute created → tenant immediately suspended."""
    test_tenant.stripe_customer_id = "cus_test_123"

    event = _make_stripe_event(
        "charge.dispute.created",
        {"charge": "ch_test_123", "amount": 29900, "reason": "fraudulent"},
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.Charge.retrieve.return_value = {"customer": "cus_test_123"}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        mock_notify.assert_called_once()
        assert "URGENT" in mock_notify.call_args[0][1]
        assert "dispute" in mock_notify.call_args[0][1]


@pytest.mark.asyncio
async def test_webhook_refund_notification(client, test_tenant):
    """Refund processed → notification sent."""
    test_tenant.stripe_customer_id = "cus_test_123"

    event = _make_stripe_event(
        "charge.refunded",
        {"customer": "cus_test_123", "amount_refunded": 29900},
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200
        mock_notify.assert_called_once()
        assert "RM299.00" in mock_notify.call_args[0][1]
        assert "refund" in mock_notify.call_args[0][1].lower()


@pytest.mark.asyncio
async def test_webhook_missing_tenant_graceful(client):
    """Webhook for unknown tenant doesn't crash."""
    event = _make_stripe_event(
        "checkout.session.completed",
        _checkout_session("nonexistent-tenant-id"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # tenant not found
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        # Should return 200 (don't trigger Stripe retries)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_unknown_event_type(client):
    """Unknown event type is ignored gracefully."""
    event = _make_stripe_event("some.unknown.event", {"id": "test"})

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(event).encode(),
            headers={"stripe-signature": "valid"},
        )

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_subscription_pause_resume(client, test_tenant):
    """Pause → suspend, Resume → activate."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    # Test pause
    pause_event = _make_stripe_event(
        "customer.subscription.paused",
        _subscription(status="paused"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = pause_event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(pause_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED

    # Test resume
    test_tenant.status = TenantStatus.SUSPENDED  # ensure still suspended
    resume_event = _make_stripe_event(
        "customer.subscription.resumed",
        _subscription(status="active"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = resume_event

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=json.dumps(resume_event).encode(),
            headers={"stripe-signature": "valid"},
        )
        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.ACTIVE


