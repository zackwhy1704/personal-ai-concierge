import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Enum as SAEnum
from sqlalchemy.orm import relationship

from app.db.types import GUID
import enum

from app.db.database import Base


class PlanType(str, enum.Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ONBOARDING = "onboarding"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    api_key_hash = Column(String(128), nullable=False)
    whatsapp_phone_number_id = Column(String(50), nullable=True)
    whatsapp_business_account_id = Column(String(50), nullable=True)
    whatsapp_access_token = Column(String(512), nullable=True)
    plan = Column(SAEnum(PlanType), default=PlanType.STARTER, nullable=False)
    status = Column(SAEnum(TenantStatus), default=TenantStatus.ONBOARDING, nullable=False)
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)
    admin_phone_numbers = Column(String(500), nullable=True)  # comma-separated
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    guardrails = relationship("GuardrailConfig", back_populates="tenant", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="tenant", cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="tenant", cascade="all, delete-orphan")
    intents = relationship("Intent", back_populates="tenant", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="tenant", cascade="all, delete-orphan")

    def get_admin_phones(self) -> list[str]:
        if not self.admin_phone_numbers:
            return []
        return [p.strip() for p in self.admin_phone_numbers.split(",")]

    def get_plan_limits(self) -> dict:
        limits = {
            PlanType.STARTER: {
                "monthly_conversations": 500,
                "overage_rate": 0.15,
                "max_documents": 50,
                "max_intents": 10,
                "max_languages": 2,
            },
            PlanType.PROFESSIONAL: {
                "monthly_conversations": 2000,
                "overage_rate": 0.10,
                "max_documents": 200,
                "max_intents": 50,
                "max_languages": 5,
            },
            PlanType.ENTERPRISE: {
                "monthly_conversations": 10000,
                "overage_rate": 0.07,
                "max_documents": -1,  # unlimited
                "max_intents": -1,
                "max_languages": -1,
            },
        }
        return limits[self.plan]
