import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Integer, Boolean
from app.db.database import Base
from app.db.types import GUID


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)
    trial_days = Column(Integer, default=30, nullable=False)
    max_redemptions = Column(Integer, nullable=True)  # None = unlimited
    times_redeemed = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # None = never expires
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    stripe_coupon_id = Column(String(100), nullable=True)
    stripe_promo_id = Column(String(100), nullable=True)

    def is_valid(self) -> bool:
        """Check if promo code can be redeemed."""
        if not self.is_active:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        if self.max_redemptions and self.times_redeemed >= self.max_redemptions:
            return False
        return True
