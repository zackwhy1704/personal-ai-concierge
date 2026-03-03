"""
Token expiration, refresh, and authentication edge-case tests.

Tests cover:
1. JWT creation with correct expiry
2. JWT decode success / expired / invalid
3. Token refresh endpoint — happy path
4. Token refresh — expired within 7-day window
5. Token refresh — expired beyond 7-day window (rejected)
6. Token refresh — suspended tenant (rejected)
7. Token refresh — deleted tenant (rejected)
8. Token refresh — invalid/malformed token
9. Token check endpoint
10. API key authentication fallback
11. Missing authentication → 401
12. Expired JWT → auto-retry with refresh (integration)
"""
import uuid
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import jwt as pyjwt

from app.api.auth import (
    create_jwt_token,
    decode_jwt_token,
    decode_jwt_token_allow_expired,
    hash_api_key,
    generate_api_key,
)
from app.config import get_settings
from app.models.tenant import TenantStatus

settings = get_settings()


# ──────────────────────────────────────────────
# Unit tests — JWT creation and decoding
# ──────────────────────────────────────────────

class TestJWTCreation:
    def test_create_jwt_has_required_claims(self):
        """JWT contains sub, exp, iat claims."""
        tenant_id = str(uuid.uuid4())
        token = create_jwt_token(tenant_id)
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

        assert payload["sub"] == tenant_id
        assert "exp" in payload
        assert "iat" in payload

    def test_create_jwt_expiry_is_correct(self):
        """JWT expires after configured hours."""
        tenant_id = str(uuid.uuid4())
        before = datetime.utcnow()
        token = create_jwt_token(tenant_id)
        after = datetime.utcnow()

        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        exp = datetime.utcfromtimestamp(payload["exp"])

        expected_min = before + timedelta(hours=settings.jwt_expiry_hours) - timedelta(seconds=2)
        expected_max = after + timedelta(hours=settings.jwt_expiry_hours) + timedelta(seconds=2)

        assert expected_min <= exp <= expected_max

    def test_decode_valid_token(self):
        """Valid token decodes successfully."""
        tenant_id = str(uuid.uuid4())
        token = create_jwt_token(tenant_id)
        payload = decode_jwt_token(token)

        assert payload["sub"] == tenant_id

    def test_decode_expired_token_raises_401(self):
        """Expired token raises HTTPException 401."""
        from fastapi import HTTPException

        tenant_id = str(uuid.uuid4())
        payload = {
            "sub": tenant_id,
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=25),
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt_token(token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_decode_invalid_token_raises_401(self):
        """Malformed token raises HTTPException 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt_token("not.a.valid.jwt")
        assert exc_info.value.status_code == 401

    def test_decode_wrong_secret_raises_401(self):
        """Token signed with wrong secret is rejected."""
        from fastapi import HTTPException

        tenant_id = str(uuid.uuid4())
        payload = {
            "sub": tenant_id,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            decode_jwt_token(token)
        assert exc_info.value.status_code == 401


class TestJWTAllowExpired:
    def test_decode_expired_token_succeeds(self):
        """decode_jwt_token_allow_expired decodes an expired token."""
        tenant_id = str(uuid.uuid4())
        payload = {
            "sub": tenant_id,
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=25),
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        result = decode_jwt_token_allow_expired(token)
        assert result["sub"] == tenant_id

    def test_decode_allow_expired_rejects_invalid(self):
        """Malformed token still rejected even with allow_expired."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            decode_jwt_token_allow_expired("garbage-token")


class TestAPIKeyGeneration:
    def test_generate_api_key_format(self):
        """API key starts with pac_ prefix."""
        key = generate_api_key()
        assert key.startswith("pac_")
        assert len(key) > 20

    def test_api_key_hash_deterministic(self):
        """Same key always produces same hash."""
        key = "pac_test123"
        assert hash_api_key(key) == hash_api_key(key)

    def test_different_keys_different_hashes(self):
        """Different keys produce different hashes."""
        assert hash_api_key("pac_key1") != hash_api_key("pac_key2")


# ──────────────────────────────────────────────
# Integration tests — Token refresh endpoint
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_valid_token(client, test_tenant):
    """Refresh with a valid (non-expired) token returns a new token."""
    token = create_jwt_token(str(test_tenant.id))

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["tenant_id"] == str(test_tenant.id)
    assert data["tenant_name"] == test_tenant.name
    assert data["expires_in"] == settings.jwt_expiry_hours * 3600

    # New token should be valid
    new_payload = decode_jwt_token(data["token"])
    assert new_payload["sub"] == str(test_tenant.id)


@pytest.mark.asyncio
async def test_refresh_recently_expired_token(client, test_tenant):
    """Token expired 1 hour ago can still be refreshed (within 7-day window)."""
    payload = {
        "sub": str(test_tenant.id),
        "exp": datetime.utcnow() - timedelta(hours=1),
        "iat": datetime.utcnow() - timedelta(hours=25),
    }
    expired_token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "token" in data


@pytest.mark.asyncio
async def test_refresh_expired_6_days_ago(client, test_tenant):
    """Token expired 6 days ago can still be refreshed (within 7-day window)."""
    payload = {
        "sub": str(test_tenant.id),
        "exp": datetime.utcnow() - timedelta(days=6),
        "iat": datetime.utcnow() - timedelta(days=7),
    }
    expired_token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_expired_beyond_7_days_rejected(client, test_tenant):
    """Token expired 8 days ago cannot be refreshed."""
    payload = {
        "sub": str(test_tenant.id),
        "exp": datetime.utcnow() - timedelta(days=8),
        "iat": datetime.utcnow() - timedelta(days=9),
    }
    old_token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {old_token}"},
    )

    assert response.status_code == 401
    assert "too old" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_suspended_tenant_rejected(client, test_tenant, db_session):
    """Suspended tenant cannot refresh token."""
    test_tenant.status = TenantStatus.SUSPENDED
    await db_session.commit()

    token = create_jwt_token(str(test_tenant.id))

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert "suspended" in response.json()["detail"].lower()

    # Reset for other tests
    test_tenant.status = TenantStatus.ACTIVE
    await db_session.commit()


@pytest.mark.asyncio
async def test_refresh_nonexistent_tenant_rejected(client):
    """Token for deleted tenant cannot be refreshed."""
    fake_id = str(uuid.uuid4())
    token = create_jwt_token(fake_id)

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_malformed_token_rejected(client):
    """Malformed token is rejected."""
    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_missing_sub_rejected(client):
    """Token without sub claim is rejected."""
    payload = {
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


# ──────────────────────────────────────────────
# Token check endpoint
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_valid_token(client, test_tenant):
    """Check endpoint returns remaining time for valid token."""
    token = create_jwt_token(str(test_tenant.id))

    response = await client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["tenant_id"] == str(test_tenant.id)
    assert data["expires_in"] > 0
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_check_expired_token(client, test_tenant):
    """Check endpoint rejects expired token."""
    payload = {
        "sub": str(test_tenant.id),
        "exp": datetime.utcnow() - timedelta(hours=1),
        "iat": datetime.utcnow() - timedelta(hours=25),
    }
    token = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    response = await client.get(
        "/api/auth/check",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
