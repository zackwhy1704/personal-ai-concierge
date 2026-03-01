import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db
from app.models.tenant import Tenant

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
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
