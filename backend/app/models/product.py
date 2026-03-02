import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, Boolean, Text, ForeignKey, JSON, Integer, Enum as SAEnum
from sqlalchemy.orm import relationship

from app.db.types import GUID
from app.db.database import Base


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    OUT_OF_STOCK = "out_of_stock"


class Product(Base):
    __tablename__ = "products"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True, index=True)
    price = Column(Float, nullable=True)
    currency = Column(String(3), default="USD", nullable=False)
    image_url = Column(String(512), nullable=True)
    action_url = Column(String(512), nullable=True)
    status = Column(SAEnum(ProductStatus), default=ProductStatus.ACTIVE, nullable=False)
    tags = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    qdrant_point_id = Column(String(100), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="products")
    upsell_attempts = relationship("UpsellAttempt", back_populates="product", cascade="all, delete-orphan")
