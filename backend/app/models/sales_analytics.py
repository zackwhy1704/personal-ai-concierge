import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, DateTime, Float, Date, Integer, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.types import GUID
from app.db.database import Base


class SalesMetricDaily(Base):
    """Daily aggregated sales metrics per tenant."""
    __tablename__ = "sales_metrics_daily"
    __table_args__ = (
        UniqueConstraint("tenant_id", "metric_date", name="uq_sales_tenant_date"),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    metric_date = Column(Date, default=date.today, nullable=False, index=True)
    total_upsell_attempts = Column(Integer, default=0, nullable=False)
    total_interest_shown = Column(Integer, default=0, nullable=False)
    total_clicks = Column(Integer, default=0, nullable=False)
    total_conversions = Column(Integer, default=0, nullable=False)
    total_revenue = Column(Float, default=0.0, nullable=False)
    conversion_rate = Column(Float, default=0.0, nullable=False)
    top_products = Column(JSON, default=list)
    top_strategies = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
