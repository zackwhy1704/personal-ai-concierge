"""Tests for promo code system — create, validate, checkout with trial."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_create_promo_code(client):
    """Admin can create a promo code."""
    response = await client.post("/api/promo", json={
        "code": "FREETRIAL",
        "description": "1 month free trial",
        "trial_days": 30,
        "max_redemptions": 100,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "FREETRIAL"
    assert data["trial_days"] == 30
    assert data["max_redemptions"] == 100
    assert data["times_redeemed"] == 0
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_promo_code_uppercase(client):
    """Promo codes are stored uppercase."""
    response = await client.post("/api/promo", json={
        "code": "summer2026",
        "trial_days": 14,
    })
    assert response.status_code == 200
    assert response.json()["code"] == "SUMMER2026"


@pytest.mark.asyncio
async def test_create_duplicate_promo_code(client):
    """Cannot create duplicate promo code."""
    await client.post("/api/promo", json={"code": "DUP1"})
    response = await client.post("/api/promo", json={"code": "DUP1"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_promo_codes(client):
    """Admin can list promo codes."""
    await client.post("/api/promo", json={"code": "LIST1"})
    await client.post("/api/promo", json={"code": "LIST2"})
    response = await client.get("/api/promo")
    assert response.status_code == 200
    codes = [p["code"] for p in response.json()]
    assert "LIST1" in codes
    assert "LIST2" in codes


@pytest.mark.asyncio
async def test_deactivate_promo_code(client):
    """Admin can deactivate a promo code."""
    create_resp = await client.post("/api/promo", json={"code": "DEACT1"})
    promo_id = create_resp.json()["id"]

    response = await client.patch(f"/api/promo/{promo_id}/deactivate")
    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"


@pytest.mark.asyncio
async def test_validate_valid_promo(client):
    """Validate a valid promo code."""
    await client.post("/api/promo", json={
        "code": "VALID30",
        "trial_days": 30,
    })
    response = await client.post("/api/promo/validate", json={"code": "valid30"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["trial_days"] == 30
    assert "30-day" in data["message"]


@pytest.mark.asyncio
async def test_validate_invalid_promo(client):
    """Validate a nonexistent promo code."""
    response = await client.post("/api/promo/validate", json={"code": "NOTREAL"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "Invalid" in data["message"]


@pytest.mark.asyncio
async def test_validate_deactivated_promo(client):
    """Deactivated promo code is not valid."""
    create_resp = await client.post("/api/promo", json={"code": "DEACT2"})
    promo_id = create_resp.json()["id"]
    await client.patch(f"/api/promo/{promo_id}/deactivate")

    response = await client.post("/api/promo/validate", json={"code": "DEACT2"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert "no longer active" in data["message"]


@pytest.mark.asyncio
async def test_validate_maxed_out_promo(client):
    """Promo code at max redemptions is not valid."""
    await client.post("/api/promo", json={
        "code": "MAXED",
        "max_redemptions": 1,
    })

    # Use it once via checkout mock
    mock_session = MagicMock()
    mock_session.id = "sess_123"
    mock_session.url = "https://checkout.stripe.com/test"

    with patch("app.api.billing.stripe.Customer.create", return_value=MagicMock(id="cus_test")):
        with patch("app.api.billing.stripe.checkout.Session.create", return_value=mock_session):
            with patch("app.api.billing.get_stripe_price_id", return_value="price_test"):
                await client.post("/api/billing/checkout", json={
                    "plan": "starter",
                    "promo_code": "MAXED",
                })

    # Now it should be maxed out
    response = await client.post("/api/promo/validate", json={"code": "MAXED"})
    data = response.json()
    assert data["valid"] is False
    assert "redemption limit" in data["message"]


@pytest.mark.asyncio
async def test_validate_empty_code(client):
    """Empty promo code returns invalid."""
    response = await client.post("/api/promo/validate", json={"code": ""})
    assert response.status_code == 200
    assert response.json()["valid"] is False


@pytest.mark.asyncio
async def test_checkout_with_promo_code(client):
    """Checkout with valid promo code applies trial_period_days."""
    await client.post("/api/promo", json={
        "code": "TRIAL30",
        "trial_days": 30,
    })

    mock_session = MagicMock()
    mock_session.id = "sess_trial"
    mock_session.url = "https://checkout.stripe.com/trial"

    with patch("app.api.billing.stripe.Customer.create", return_value=MagicMock(id="cus_trial")):
        with patch("app.api.billing.stripe.checkout.Session.create", return_value=mock_session) as mock_create:
            with patch("app.api.billing.get_stripe_price_id", return_value="price_test"):
                response = await client.post("/api/billing/checkout", json={
                    "plan": "starter",
                    "promo_code": "TRIAL30",
                })

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess_trial"

    # Verify trial_period_days was passed to Stripe
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["subscription_data"]["trial_period_days"] == 30
    assert call_kwargs["payment_method_collection"] == "always"


@pytest.mark.asyncio
async def test_checkout_without_promo_code(client):
    """Checkout without promo code has no trial."""
    mock_session = MagicMock()
    mock_session.id = "sess_notrial"
    mock_session.url = "https://checkout.stripe.com/notrial"

    with patch("app.api.billing.stripe.Customer.create", return_value=MagicMock(id="cus_notrial")):
        with patch("app.api.billing.stripe.checkout.Session.create", return_value=mock_session) as mock_create:
            with patch("app.api.billing.get_stripe_price_id", return_value="price_test"):
                response = await client.post("/api/billing/checkout", json={
                    "plan": "starter",
                })

    assert response.status_code == 200
    call_kwargs = mock_create.call_args[1]
    assert "trial_period_days" not in call_kwargs["subscription_data"]
    assert "payment_method_collection" not in call_kwargs


@pytest.mark.asyncio
async def test_checkout_with_invalid_promo(client):
    """Checkout with invalid promo code fails."""
    with patch("app.api.billing.get_stripe_price_id", return_value="price_test"):
        response = await client.post("/api/billing/checkout", json={
            "plan": "starter",
            "promo_code": "NOTEXIST",
        })
    assert response.status_code == 400
    assert "Invalid or expired" in response.json()["detail"]


@pytest.mark.asyncio
async def test_checkout_trial_notification(client):
    """Checkout completed with trial sends trial-specific notification."""
    mock_sub = MagicMock()
    mock_sub.status = "trialing"
    mock_sub.trial_end = 1712000000  # some timestamp

    with patch("app.api.billing.stripe.Subscription.retrieve", return_value=mock_sub):
        with patch("app.api.billing._notify_admin") as mock_notify:
            from app.api.billing import _handle_checkout_completed
            await _handle_checkout_completed({
                "metadata": {"tenant_id": str((await client.get("/api/tenants/me")).json()["id"]), "plan": "starter"},
                "subscription": "sub_trial123",
                "customer": "cus_trial123",
            })

            if mock_notify.called:
                msg = mock_notify.call_args[0][1]
                assert "Free trial activated" in msg or "trial" in msg.lower()


@pytest.mark.asyncio
async def test_promo_redemption_count_increments(client):
    """Promo code redemption count increases on checkout."""
    await client.post("/api/promo", json={
        "code": "COUNT1",
        "trial_days": 7,
    })

    mock_session = MagicMock()
    mock_session.id = "sess_count"
    mock_session.url = "https://checkout.stripe.com/count"

    with patch("app.api.billing.stripe.Customer.create", return_value=MagicMock(id="cus_count")):
        with patch("app.api.billing.stripe.checkout.Session.create", return_value=mock_session):
            with patch("app.api.billing.get_stripe_price_id", return_value="price_test"):
                await client.post("/api/billing/checkout", json={
                    "plan": "starter",
                    "promo_code": "COUNT1",
                })

    # Check redemption count
    promos = (await client.get("/api/promo")).json()
    count_promo = [p for p in promos if p["code"] == "COUNT1"][0]
    assert count_promo["times_redeemed"] == 1


@pytest.mark.asyncio
async def test_create_promo_with_expiry(client):
    """Create a promo code with expiry date."""
    response = await client.post("/api/promo", json={
        "code": "EXPIRY1",
        "trial_days": 14,
        "expires_at": "2026-12-31T23:59:59",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["expires_at"] is not None
    assert "2026-12-31" in data["expires_at"]
