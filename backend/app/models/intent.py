import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.db.types import GUID

from app.db.database import Base


class Intent(Base):
    __tablename__ = "intents"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    examples = Column(JSON, nullable=False, default=list)  # list of example utterances
    action_type = Column(String(50), nullable=False)  # "link", "api_call", "flow", "rag_answer"
    action_config = Column(JSON, nullable=False, default=dict)
    # action_config example:
    # {"url": "https://hotel.com/book", "method": "POST", "params": ["check_in", "check_out"]}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="intents")
