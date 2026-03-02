import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import relationship

from app.db.types import GUID
import enum

from app.db.database import Base


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    ESCALATED = "escalated"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(GUID, ForeignKey("tenants.id"), nullable=False, index=True)
    guest_phone = Column(String(50), nullable=False, index=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(SAEnum(ConversationStatus), default=ConversationStatus.ACTIVE, nullable=False)
    message_count = Column(Integer, default=0, nullable=False)
    total_tokens_used = Column(Integer, default=0, nullable=False)
    summary = Column(Text, nullable=True)  # rolling summary of older messages
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_message_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")
    upsell_attempts = relationship("UpsellAttempt", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    conversation_id = Column(GUID, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(SAEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    detected_intent = Column(String(100), nullable=True)
    tokens_used = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
