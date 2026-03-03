import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
import jwt as pyjwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)
settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return f"pac_{secrets.token_urlsafe(32)}"


def create_jwt_token(tenant_id: str) -> str:
    payload = {
        "sub": tenant_id,
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expiry_hours),
        "iat": datetime.utcnow(),
    }
    return pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt_token(token: str) -> Optional[dict]:
    try:
        payload = pyjwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def decode_jwt_token_allow_expired(token: str) -> Optional[dict]:
    """Decode a JWT token even if expired (for refresh flow)."""
    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        return payload
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_tenant(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    api_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Authenticate via JWT bearer token or API key."""
    # Try JWT first
    if credentials:
        payload = decode_jwt_token(credentials.credentials)
        tenant_id = payload.get("sub")
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=401, detail="Tenant not found")
        return tenant

    # Try API key
    if api_key:
        key_hash = hash_api_key(api_key)
        result = await db.execute(
            select(Tenant).where(Tenant.api_key_hash == key_hash)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return tenant

    raise HTTPException(status_code=401, detail="Authentication required")


async def verify_admin(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> bool:
    """Verify platform admin access."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    if credentials.credentials != settings.admin_api_key:
        # Also try JWT
        try:
            payload = decode_jwt_token(credentials.credentials)
            if payload.get("admin"):
                return True
        except HTTPException:
            pass
        raise HTTPException(status_code=403, detail="Admin access required")

    return True


# ──────────────────────────────────────────────
# Token refresh endpoint
# ──────────────────────────────────────────────

@router.post("/refresh")
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer()),
    db: AsyncSession = Depends(get_db),
):
    """Refresh a JWT token. Accepts tokens up to 7 days past expiry.

    Returns a new JWT with a fresh expiry window. The old token's tenant
    must still exist and not be suspended.
    """
    token = credentials.credentials

    # Decode without verifying expiry
    payload = decode_jwt_token_allow_expired(token)
    tenant_id = payload.get("sub")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Reject tokens expired more than 7 days ago
    exp = payload.get("exp", 0)
    max_refresh_window = datetime.utcnow() - timedelta(days=7)
    if datetime.utcfromtimestamp(exp) < max_refresh_window:
        raise HTTPException(
            status_code=401,
            detail="Token too old to refresh. Please log in again.",
        )

    # Verify tenant still exists and is not suspended
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found")
    from app.models.tenant import TenantStatus
    if tenant.status == TenantStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Account is suspended")

    new_token = create_jwt_token(str(tenant.id))
    return {
        "token": new_token,
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "expires_in": settings.jwt_expiry_hours * 3600,
    }


@router.get("/check")
async def check_token(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer()),
):
    """Check if a token is still valid and return time until expiry."""
    payload = decode_jwt_token(credentials.credentials)
    exp = payload.get("exp", 0)
    now = datetime.utcnow().timestamp()
    remaining = int(exp - now)
    return {
        "valid": True,
        "tenant_id": payload.get("sub"),
        "expires_in": remaining,
        "expires_at": datetime.utcfromtimestamp(exp).isoformat(),
    }
