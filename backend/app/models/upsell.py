import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, Boolean, Text, ForeignKey, JSON, Integer, Enum as SAEnum
from sqlalchemy.orm import relationship

from app.db.types import GUID
from app.db.database import Base


class UpsellTriggerType(str, enum.Enum):
    INTENT_MATCH = "intent_match"
    KEYWORD = "keyword"
    CATEGORY_CONTEXT = "category_context"
    PROACTIVE = "proactive"
    CROSS_SELL = "cross_sell"


class UpsellOutcome(str, enum.Enum):
    PRESENTED = "presented"
    INTEREST_SHOWN = "interest_shown"
    CLICKED = "clicked"
    CONVERTED = "converted"
    DISMISSED = "dismissed"
    REJECTED = "rejected"


class UpsellStrategy(Base):
    __tablename__ = "upsell_strategies"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    trigger_type = Column(SAEnum(UpsellTriggerType), nullable=False)
    trigger_config = Column(JSON, nullable=False, default=dict)
    prompt_template = Column(Text, nullable=True)
    max_attempts_per_session = Column(Integer, default=2, nullable=False)
    priority = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    ab_test_group = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="upsell_strategies")
    upsell_attempts = relationship("UpsellAttempt", back_populates="strategy", cascade="all, delete-orphan")


class UpsellAttempt(Base):
    __tablename__ = "upsell_attempts"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    conversation_id = Column(GUID, ForeignKey("conversations.id"), nullable=True, index=True)
    product_id = Column(GUID, ForeignKey("products.id"), nullable=False, index=True)
    strategy_id = Column(GUID, ForeignKey("upsell_strategies.id"), nullable=True, index=True)
    message_id = Column(GUID, ForeignKey("messages.id"), nullable=True)

    outcome = Column(SAEnum(UpsellOutcome), default=UpsellOutcome.PRESENTED, nullable=False)
    trigger_context = Column(JSON, default=dict)
    revenue_attributed = Column(Float, default=0.0, nullable=False)
    guest_phone = Column(String(50), nullable=True, index=True)
    session_id = Column(String(100), nullable=True, index=True)
    ab_test_group = Column(String(50), nullable=True)

    presented_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    outcome_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="upsell_attempts_rel")
    conversation = relationship("Conversation", back_populates="upsell_attempts")
    product = relationship("Product", back_populates="upsell_attempts")
    strategy = relationship("UpsellStrategy", back_populates="upsell_attempts")
