"""
Comprehensive payment/billing edge-case tests.

Expands on test_billing.py to cover:
1. Payment success — correct RM amounts in notifications
2. Payment failed — 2nd attempt (warning, not suspended)
3. Payment failed — 3rd attempt (suspended)
4. Payment failed — amount_due is null/zero
5. Checkout — existing stripe customer reused
6. Checkout — each plan type (starter, professional, enterprise)
7. Subscription cancelled — clears subscription_id
8. Subscription updated — plan upgrade (starter → professional)
9. Subscription updated — plan downgrade (enterprise → starter)
10. Subscription updated — past_due status notification
11. Subscription updated — renewal (active, no cancel)
12. Refund — correct RM amount
13. Refund — zero amount edge case
14. Refund — missing customer_id
15. Dispute — Stripe Charge.retrieve fails
16. Dispute — missing charge_id
17. Invoice — empty lines.data (IndexError guard)
18. Invoice — null amount fields
19. Invoice — missing subscription_id (skipped)
20. Webhook — duplicate event processing
21. Webhook — empty payload
22. Webhook — handler exception → returns 200
23. Cancel endpoint — with active subscription
24. Reactivate endpoint — with active subscription
25. Subscription status — with Stripe subscription
26. Subscription status — Stripe returns InvalidRequestError
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from app.models.tenant import PlanType, TenantStatus


# ──────────────────────────────────────────────
# Stripe Event Factories
# ──────────────────────────────────────────────

def _event(event_type: str, data: dict, event_id: str = "evt_test_123") -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": data}}


def _checkout(tenant_id: str, plan: str = "professional") -> dict:
    return {
        "id": "cs_test_123",
        "customer": "cus_test_123",
        "subscription": "sub_test_123",
        "metadata": {"tenant_id": tenant_id, "plan": plan},
    }


def _invoice(
    subscription_id: str = "sub_test_123",
    amount_paid: int = 280000,
    amount_due: int = 280000,
    attempt: int = 1,
    lines_data: list | None = None,
    next_payment_attempt: int | None = None,
) -> dict:
    if lines_data is None:
        lines_data = [{"period": {"end": int(datetime(2026, 4, 1).timestamp())}}]
    result = {
        "id": "in_test_123",
        "subscription": subscription_id,
        "customer": "cus_test_123",
        "amount_paid": amount_paid,
        "amount_due": amount_due,
        "attempt_count": attempt,
        "lines": {"data": lines_data},
    }
    if next_payment_attempt is not None:
        result["next_payment_attempt"] = next_payment_attempt
    return result


def _subscription(
    subscription_id: str = "sub_test_123",
    status: str = "active",
    cancel_at_period_end: bool = False,
    price_id: str = "price_professional",
    items_data: list | None = None,
) -> dict:
    if items_data is None:
        items_data = [{"price": {"id": price_id}}]
    return {
        "id": subscription_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "current_period_end": int(datetime(2026, 4, 1).timestamp()),
        "items": {"data": items_data},
    }


def _mock_db_session(tenant):
    """Create a mocked async DB session that returns the given tenant."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = tenant
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session


async def _post_webhook(client, event):
    """Helper to post a webhook event to the Stripe endpoint."""
    return await client.post(
        "/api/billing/webhook/stripe",
        content=json.dumps(event).encode(),
        headers={"stripe-signature": "valid"},
    )


# ──────────────────────────────────────────────
# Payment Success Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_success_rm_amount(client, test_tenant):
    """Payment success notification shows correct RM amount (280000 cents → RM2800.00)."""
    event = _event("invoice.payment_succeeded", _invoice(amount_paid=280000))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        mock_notify.assert_called_once()
        msg = mock_notify.call_args[0][1]
        assert "RM2800.00" in msg
        assert "Payment received" in msg


@pytest.mark.asyncio
async def test_payment_success_starter_amount(client, test_tenant):
    """Starter plan payment (RM780 = 78000 cents)."""
    test_tenant.plan = PlanType.STARTER
    event = _event("invoice.payment_succeeded", _invoice(amount_paid=78000))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "RM780.00" in msg


@pytest.mark.asyncio
async def test_payment_success_reactivates_suspended(client, test_tenant):
    """Payment success reactivates a previously suspended tenant."""
    test_tenant.status = TenantStatus.SUSPENDED
    event = _event("invoice.payment_succeeded", _invoice())

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.ACTIVE


@pytest.mark.asyncio
async def test_payment_success_with_next_billing_date(client, test_tenant):
    """Payment success shows next billing date from invoice period."""
    inv = _invoice(
        lines_data=[{"period": {"end": int(datetime(2026, 5, 15).timestamp())}}]
    )
    event = _event("invoice.payment_succeeded", inv)

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "May 15, 2026" in msg


@pytest.mark.asyncio
async def test_payment_success_empty_lines(client, test_tenant):
    """Payment success with empty lines.data doesn't crash."""
    inv = _invoice(lines_data=[])
    event = _event("invoice.payment_succeeded", inv)

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_payment_success_no_subscription_id(client, test_tenant):
    """Payment success with no subscription_id is gracefully skipped."""
    inv = _invoice()
    inv["subscription"] = None
    event = _event("invoice.payment_succeeded", inv)

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_payment_success_tenant_lookup_by_customer_id(client, test_tenant):
    """Falls back to customer_id lookup when subscription_id doesn't match."""
    test_tenant.stripe_customer_id = "cus_test_123"
    test_tenant.stripe_subscription_id = "sub_different"

    inv = _invoice(subscription_id="sub_unknown")
    event = _event("invoice.payment_succeeded", inv)

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event

        # First query (by subscription_id) returns None, second (by customer_id) returns tenant
        mock_session = AsyncMock()
        result_none = MagicMock()
        result_none.scalar_one_or_none.return_value = None
        result_found = MagicMock()
        result_found.scalar_one_or_none.return_value = test_tenant
        mock_session.execute = AsyncMock(side_effect=[result_none, result_found])
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_sf.return_value = mock_session

        response = await _post_webhook(client, event)
        assert response.status_code == 200
        mock_notify.assert_called_once()


# ──────────────────────────────────────────────
# Payment Failed Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payment_failed_second_attempt(client, test_tenant):
    """Second payment failure sends warning, does NOT suspend."""
    event = _event(
        "invoice.payment_failed",
        _invoice(attempt=2, next_payment_attempt=int(datetime(2026, 4, 10).timestamp())),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "attempt 2/3" in msg
        assert test_tenant.status != TenantStatus.SUSPENDED


@pytest.mark.asyncio
async def test_payment_failed_fourth_attempt(client, test_tenant):
    """4th attempt (>= 3) still suspends."""
    event = _event("invoice.payment_failed", _invoice(attempt=4))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        msg = mock_notify.call_args[0][1]
        assert "URGENT" in msg


@pytest.mark.asyncio
async def test_payment_failed_zero_amount(client, test_tenant):
    """Payment failure with zero amount_due doesn't crash."""
    event = _event("invoice.payment_failed", _invoice(amount_due=0, attempt=1))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)
        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "RM0.00" in msg


@pytest.mark.asyncio
async def test_payment_failed_no_next_attempt(client, test_tenant):
    """Payment failure with no next_payment_attempt shows empty date."""
    inv = _invoice(attempt=1)
    inv.pop("next_payment_attempt", None)
    event = _event("invoice.payment_failed", inv)

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_payment_failed_no_subscription(client):
    """Payment failure with no subscription_id is skipped."""
    inv = _invoice()
    inv["subscription"] = None
    event = _event("invoice.payment_failed", inv)

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


# ──────────────────────────────────────────────
# Checkout Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkout_starter_plan(client):
    """Checkout for starter plan."""
    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.settings") as mock_settings:
        mock_settings.stripe_starter_price_id = "price_starter_test"
        mock_settings.stripe_professional_price_id = "price_professional_test"
        mock_settings.stripe_enterprise_price_id = "price_enterprise_test"
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new")
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test", id="cs_starter"
        )

        response = await client.post("/api/billing/checkout", json={
            "plan": "starter",
            "success_url": "https://example.com/ok",
            "cancel_url": "https://example.com/cancel",
        })

        assert response.status_code == 200
        assert response.json()["session_id"] == "cs_starter"


@pytest.mark.asyncio
async def test_checkout_enterprise_plan(client):
    """Checkout for enterprise plan."""
    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.settings") as mock_settings:
        mock_settings.stripe_starter_price_id = "price_starter_test"
        mock_settings.stripe_professional_price_id = "price_professional_test"
        mock_settings.stripe_enterprise_price_id = "price_enterprise_test"
        mock_stripe.Customer.create.return_value = MagicMock(id="cus_new")
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/ent", id="cs_enterprise"
        )

        response = await client.post("/api/billing/checkout", json={
            "plan": "enterprise",
            "success_url": "https://example.com/ok",
            "cancel_url": "https://example.com/cancel",
        })

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_checkout_reuses_existing_customer(client, test_tenant):
    """If tenant already has stripe_customer_id, Customer.create is not called."""
    test_tenant.stripe_customer_id = "cus_existing_123"

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.settings") as mock_settings:
        mock_settings.stripe_starter_price_id = "price_starter"
        mock_settings.stripe_professional_price_id = "price_professional"
        mock_settings.stripe_enterprise_price_id = "price_enterprise"
        mock_stripe.checkout.Session.create.return_value = MagicMock(
            url="https://checkout.stripe.com/test", id="cs_reuse"
        )

        response = await client.post("/api/billing/checkout", json={
            "plan": "professional",
            "success_url": "https://example.com/ok",
            "cancel_url": "https://example.com/cancel",
        })

        assert response.status_code == 200
        mock_stripe.Customer.create.assert_not_called()


@pytest.mark.asyncio
async def test_checkout_empty_price_id(client):
    """Checkout fails when price_id is not configured (empty string)."""
    with patch("app.api.billing.get_stripe_price_id", return_value=""):
        response = await client.post("/api/billing/checkout", json={
            "plan": "starter",
        })
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_checkout_completed_activates_tenant(client, test_tenant, db_session):
    """Checkout completed sets tenant to ACTIVE with correct plan and IDs."""
    test_tenant.status = TenantStatus.ONBOARDING
    event = _event("checkout.session.completed", _checkout(str(test_tenant.id), "enterprise"))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.ACTIVE
        assert test_tenant.plan == PlanType.ENTERPRISE
        assert test_tenant.stripe_customer_id == "cus_test_123"
        assert test_tenant.stripe_subscription_id == "sub_test_123"

        msg = mock_notify.call_args[0][1]
        assert "Enterprise" in msg
        assert "RM6,800" in msg


@pytest.mark.asyncio
async def test_checkout_completed_missing_metadata(client):
    """Checkout without tenant_id in metadata is handled gracefully."""
    data = {
        "id": "cs_test",
        "customer": "cus_test",
        "subscription": "sub_test",
        "metadata": {},
    }
    event = _event("checkout.session.completed", data)

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


# ──────────────────────────────────────────────
# Subscription Update Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_plan_upgrade(client, test_tenant):
    """Subscription updated with new price → plan upgraded."""
    test_tenant.stripe_subscription_id = "sub_test_123"
    test_tenant.plan = PlanType.STARTER

    event = _event(
        "customer.subscription.updated",
        _subscription(price_id="price_professional"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {"price_professional": PlanType.PROFESSIONAL}

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.plan == PlanType.PROFESSIONAL
        msg = mock_notify.call_args[0][1]
        assert "Starter" in msg
        assert "Professional" in msg
        assert "RM2,800" in msg


@pytest.mark.asyncio
async def test_subscription_plan_downgrade(client, test_tenant):
    """Subscription updated with lower price → plan downgraded."""
    test_tenant.stripe_subscription_id = "sub_test_123"
    test_tenant.plan = PlanType.ENTERPRISE

    event = _event(
        "customer.subscription.updated",
        _subscription(price_id="price_starter"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {"price_starter": PlanType.STARTER}

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.plan == PlanType.STARTER


@pytest.mark.asyncio
async def test_subscription_past_due_notification(client, test_tenant):
    """Subscription status past_due sends warning notification."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    event = _event(
        "customer.subscription.updated",
        _subscription(status="past_due"),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {}

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "past due" in msg


@pytest.mark.asyncio
async def test_subscription_renewed_notification(client, test_tenant):
    """Active subscription renewal sends success notification."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    event = _event(
        "customer.subscription.updated",
        _subscription(status="active", cancel_at_period_end=False),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {}

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        mock_notify.assert_called()
        msg = mock_notify.call_args[0][1]
        assert "renewed" in msg.lower()


@pytest.mark.asyncio
async def test_subscription_updated_empty_items(client, test_tenant):
    """Subscription updated with no items doesn't crash."""
    test_tenant.stripe_subscription_id = "sub_test_123"

    event = _event(
        "customer.subscription.updated",
        _subscription(items_data=[]),
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock), \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan") as mock_price_map:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)
        mock_price_map.return_value = {}

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_subscription_updated_no_subscription_id(client):
    """Subscription updated without id is skipped."""
    sub = _subscription()
    sub["id"] = None
    event = _event("customer.subscription.updated", sub)

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


# ──────────────────────────────────────────────
# Cancellation & Deletion Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_deleted_clears_ids(client, test_tenant):
    """Full cancellation clears subscription_id and suspends."""
    test_tenant.stripe_subscription_id = "sub_test_123"
    test_tenant.status = TenantStatus.ACTIVE

    event = _event("customer.subscription.deleted", _subscription())

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        assert test_tenant.stripe_subscription_id is None
        msg = mock_notify.call_args[0][1]
        assert "cancelled" in msg
        assert "data" in msg.lower()  # mentions data is preserved


@pytest.mark.asyncio
async def test_cancel_endpoint_with_subscription(client, test_tenant):
    """Cancel endpoint calls Stripe to set cancel_at_period_end."""
    test_tenant.stripe_subscription_id = "sub_active_123"

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.modify.return_value = MagicMock(
            current_period_end=int(datetime(2026, 4, 1).timestamp())
        )

        response = await client.post("/api/billing/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelling"
        assert "2026" in data["cancel_at"]
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_active_123", cancel_at_period_end=True
        )


@pytest.mark.asyncio
async def test_reactivate_endpoint_with_subscription(client, test_tenant):
    """Reactivate endpoint sets cancel_at_period_end=False."""
    test_tenant.stripe_subscription_id = "sub_active_123"

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.modify.return_value = MagicMock()

        response = await client.post("/api/billing/reactivate")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        mock_stripe.Subscription.modify.assert_called_once_with(
            "sub_active_123", cancel_at_period_end=False
        )


# ──────────────────────────────────────────────
# Refund Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refund_rm_amount(client, test_tenant):
    """Refund notification shows correct RM amount."""
    test_tenant.stripe_customer_id = "cus_test_123"
    event = _event("charge.refunded", {"customer": "cus_test_123", "amount_refunded": 78000})

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "RM780.00" in msg
        assert "refund" in msg.lower()


@pytest.mark.asyncio
async def test_refund_zero_amount(client, test_tenant):
    """Refund of zero amount doesn't crash."""
    test_tenant.stripe_customer_id = "cus_test_123"
    event = _event("charge.refunded", {"customer": "cus_test_123", "amount_refunded": 0})

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)
        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "RM0.00" in msg


@pytest.mark.asyncio
async def test_refund_missing_customer(client):
    """Refund with no customer_id is skipped."""
    event = _event("charge.refunded", {"customer": None, "amount_refunded": 10000})

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_refund_tenant_not_found(client):
    """Refund for unknown customer is gracefully handled."""
    event = _event("charge.refunded", {"customer": "cus_unknown", "amount_refunded": 10000})

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(None)  # tenant not found

        response = await _post_webhook(client, event)
        assert response.status_code == 200


# ──────────────────────────────────────────────
# Dispute Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispute_charge_retrieve_fails(client, test_tenant):
    """Dispute when Stripe Charge.retrieve fails → doesn't crash."""
    event = _event("charge.dispute.created", {
        "charge": "ch_test_123", "amount": 280000, "reason": "product_not_received"
    })

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.Charge.retrieve.side_effect = Exception("Stripe API error")

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispute_missing_charge_id(client):
    """Dispute with no charge_id is skipped."""
    event = _event("charge.dispute.created", {
        "charge": None, "amount": 10000, "reason": "unknown"
    })

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Webhook.construct_event.return_value = event
        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_dispute_rm_amount(client, test_tenant):
    """Dispute notification shows RM amount."""
    test_tenant.stripe_customer_id = "cus_test_123"
    event = _event("charge.dispute.created", {
        "charge": "ch_test", "amount": 680000, "reason": "duplicate"
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.Charge.retrieve.return_value = {"customer": "cus_test_123"}
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        msg = mock_notify.call_args[0][1]
        assert "RM6800.00" in msg
        assert "duplicate" in msg


# ──────────────────────────────────────────────
# Subscription Status Endpoint Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscription_status_with_stripe(client, test_tenant):
    """Subscription status with active Stripe subscription."""
    test_tenant.stripe_subscription_id = "sub_active_123"

    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.retrieve.return_value = MagicMock(
            status="active",
            current_period_end=int(datetime(2026, 4, 1).timestamp()),
            cancel_at_period_end=False,
        )

        response = await client.get("/api/billing/subscription")

        assert response.status_code == 200
        data = response.json()
        assert data["has_subscription"] is True
        assert data["status"] == "active"
        assert data["cancel_at_period_end"] is False


@pytest.mark.asyncio
async def test_subscription_status_stripe_invalid_request(client, test_tenant):
    """Subscription status when Stripe returns InvalidRequestError."""
    test_tenant.stripe_subscription_id = "sub_deleted_123"

    import stripe as _stripe
    with patch("app.api.billing.stripe") as mock_stripe:
        mock_stripe.Subscription.retrieve.side_effect = _stripe.error.InvalidRequestError(
            "No such subscription", param=None
        )
        mock_stripe.error = _stripe.error

        response = await client.get("/api/billing/subscription")

        assert response.status_code == 200
        data = response.json()
        assert data["has_subscription"] is False
        assert data["status"] == "invalid"


# ──────────────────────────────────────────────
# Webhook Infrastructure Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_handler_exception_returns_200(client, test_tenant):
    """Handler exception still returns 200 (avoid Stripe retries)."""
    event = _event("checkout.session.completed", _checkout(str(test_tenant.id)))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._handle_checkout_completed", new_callable=AsyncMock) as mock_handler:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_handler.side_effect = RuntimeError("Unexpected error")

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_empty_body(client):
    """Webhook with empty body returns 400."""
    import stripe as _stripe

    with patch("app.api.billing.stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = ValueError("Invalid payload")

        response = await client.post(
            "/api/billing/webhook/stripe",
            content=b"",
            headers={"stripe-signature": "sig"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_webhook_duplicate_event_ids(client, test_tenant):
    """Same event processed twice doesn't crash (no idempotency yet)."""
    event = _event(
        "invoice.payment_succeeded",
        _invoice(amount_paid=78000),
        event_id="evt_duplicate_123",
    )

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        # Process same event twice
        r1 = await _post_webhook(client, event)
        r2 = await _post_webhook(client, event)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert mock_notify.call_count == 2  # processed twice (no dedup)


# ──────────────────────────────────────────────
# Notification Edge Cases
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_no_whatsapp_config(client, test_tenant):
    """Notification skipped if tenant has no WhatsApp config."""
    test_tenant.whatsapp_phone_number_id = None
    test_tenant.whatsapp_access_token = None

    event = _event("invoice.payment_succeeded", _invoice())

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        # Should not crash even though WhatsApp is not configured
        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_notify_no_admin_phones(client, test_tenant):
    """Notification skipped if tenant has no admin phone numbers."""
    test_tenant.admin_phone_numbers = None

    event = _event("invoice.payment_succeeded", _invoice())

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_pause_and_resume_full_cycle(client, test_tenant):
    """Full cycle: active → paused → resumed."""
    test_tenant.stripe_subscription_id = "sub_test_123"
    test_tenant.status = TenantStatus.ACTIVE

    # Pause
    pause_event = _event("customer.subscription.paused", _subscription(status="paused"))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = pause_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, pause_event)
        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.SUSPENDED
        msg = mock_notify.call_args[0][1]
        assert "paused" in msg.lower()

    # Resume
    resume_event = _event("customer.subscription.resumed", _subscription(status="active"))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = resume_event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, resume_event)
        assert response.status_code == 200
        assert test_tenant.status == TenantStatus.ACTIVE
        msg = mock_notify.call_args[0][1]
        assert "resumed" in msg.lower()


# ──────────────────────────────────────────────
# Multi-Currency Tests (SGD)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sgd_checkout_notification(client, test_tenant):
    """SGD tenant checkout notification shows S$ symbol."""
    test_tenant.currency = "SGD"
    event = _event("checkout.session.completed", _checkout(str(test_tenant.id), "starter"))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "S$260" in msg
        assert "Starter" in msg

    test_tenant.currency = "MYR"  # reset


@pytest.mark.asyncio
async def test_sgd_payment_success_notification(client, test_tenant):
    """SGD tenant payment success shows S$ symbol."""
    test_tenant.currency = "SGD"
    event = _event("invoice.payment_succeeded", _invoice(amount_paid=26000))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "S$260.00" in msg

    test_tenant.currency = "MYR"  # reset


@pytest.mark.asyncio
async def test_sgd_payment_failed_notification(client, test_tenant):
    """SGD tenant payment failure shows S$ symbol."""
    test_tenant.currency = "SGD"
    event = _event("invoice.payment_failed", _invoice(
        amount_due=93000, attempt=4, next_payment_attempt=None
    ))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "S$930.00" in msg

    test_tenant.currency = "MYR"  # reset


@pytest.mark.asyncio
async def test_sgd_plan_upgrade_notification(client, test_tenant):
    """SGD tenant plan change notification shows S$ formatted price."""
    test_tenant.currency = "SGD"
    test_tenant.stripe_subscription_id = "sub_test_123"
    test_tenant.plan = PlanType.STARTER

    event = _event("customer.subscription.updated", _subscription(
        price_id="price_professional_sgd"
    ))

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf, \
         patch("app.api.billing._get_price_to_plan", return_value={
             "price_professional_sgd": PlanType.PROFESSIONAL,
         }):

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        assert test_tenant.plan == PlanType.PROFESSIONAL
        msg = mock_notify.call_args[0][1]
        assert "S$930" in msg

    test_tenant.currency = "MYR"  # reset


@pytest.mark.asyncio
async def test_sgd_refund_notification(client, test_tenant):
    """SGD tenant refund notification shows S$ symbol."""
    test_tenant.currency = "SGD"
    event = _event("charge.refunded", {
        "id": "ch_test_123",
        "customer": "cus_test_123",
        "amount_refunded": 26000,
    })

    with patch("app.api.billing.stripe") as mock_stripe, \
         patch("app.api.billing._notify_admin", new_callable=AsyncMock) as mock_notify, \
         patch("app.api.billing.async_session_factory") as mock_sf:

        mock_stripe.Webhook.construct_event.return_value = event
        mock_sf.return_value = _mock_db_session(test_tenant)

        response = await _post_webhook(client, event)

        assert response.status_code == 200
        msg = mock_notify.call_args[0][1]
        assert "S$260.00" in msg

    test_tenant.currency = "MYR"  # reset


@pytest.mark.asyncio
async def test_pricing_endpoint_myr(client):
    """Pricing endpoint returns MYR plans."""
    response = await client.get("/api/billing/pricing?currency=MYR")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "MYR"
    assert data["symbol"] == "RM"
    assert len(data["plans"]) == 3
    assert data["plans"][0]["price"] == 780
    assert data["plans"][1]["price"] == 2800
    assert data["plans"][2]["price"] == 6800


@pytest.mark.asyncio
async def test_pricing_endpoint_sgd(client):
    """Pricing endpoint returns SGD plans."""
    response = await client.get("/api/billing/pricing?currency=SGD")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "SGD"
    assert data["symbol"] == "S$"
    assert len(data["plans"]) == 3
    assert data["plans"][0]["price"] == 260
    assert data["plans"][1]["price"] == 930
    assert data["plans"][2]["price"] == 2260


@pytest.mark.asyncio
async def test_pricing_endpoint_invalid_currency(client):
    """Pricing endpoint rejects unsupported currency."""
    response = await client.get("/api/billing/pricing?currency=EUR")
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sgd_overage_rates():
    """SGD tenant gets correct overage rates from pricing config."""
    from app.pricing import get_overage_rate
    assert get_overage_rate("SGD", "starter") == 0.22
    assert get_overage_rate("SGD", "professional") == 0.15
    assert get_overage_rate("SGD", "enterprise") == 0.10


@pytest.mark.asyncio
async def test_myr_overage_rates():
    """MYR tenant gets correct overage rates from pricing config."""
    from app.pricing import get_overage_rate
    assert get_overage_rate("MYR", "starter") == 0.65
    assert get_overage_rate("MYR", "professional") == 0.45
    assert get_overage_rate("MYR", "enterprise") == 0.30
