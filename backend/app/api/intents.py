import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.intent import Intent
from app.api.auth import get_current_tenant
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/intents", tags=["intents"])


class IntentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    examples: list[str]  # example utterances for this intent
    action_type: str  # "link", "api_call", "flow", "rag_answer"
    action_config: dict = {}


class IntentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    examples: list[str]
    action_type: str
    action_config: dict
    created_at: str


class IntentTestRequest(BaseModel):
    message: str


class IntentTestResponse(BaseModel):
    intent_name: Optional[str]
    confidence: Optional[float]
    action_type: Optional[str]
    matched_example: Optional[str]


@router.post("", response_model=IntentResponse)
async def create_intent(
    data: IntentCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new intent with example utterances."""
    limits = tenant.get_plan_limits()
    max_intents = limits["max_intents"]

    if max_intents > 0:
        result = await db.execute(
            select(Intent).where(Intent.tenant_id == tenant.id)
        )
        current_count = len(result.scalars().all())
        if current_count >= max_intents:
            raise HTTPException(
                status_code=403,
                detail=f"Plan limit reached: max {max_intents} intents allowed",
            )

    if len(data.examples) < 2:
        raise HTTPException(
            status_code=422,
            detail="At least 2 example utterances are required",
        )

    intent = Intent(
        tenant_id=tenant.id,
        name=data.name,
        description=data.description,
        examples=data.examples,
        action_type=data.action_type,
        action_config=data.action_config,
    )
    db.add(intent)
    await db.flush()

    # Upsert intent examples into vector store
    vector_store = VectorStoreService()
    try:
        await vector_store.upsert_intent_examples(
            tenant_id=str(tenant.id),
            intent_name=data.name,
            examples=data.examples,
            action_type=data.action_type,
            action_config=data.action_config,
        )
    finally:
        await vector_store.close()

    return IntentResponse(
        id=str(intent.id),
        name=intent.name,
        description=intent.description,
        examples=intent.examples,
        action_type=intent.action_type,
        action_config=intent.action_config,
        created_at=intent.created_at.isoformat(),
    )


@router.get("", response_model=list[IntentResponse])
async def list_intents(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all intents for the current tenant."""
    result = await db.execute(
        select(Intent)
        .where(Intent.tenant_id == tenant.id)
        .order_by(Intent.created_at)
    )
    intents = result.scalars().all()
    return [
        IntentResponse(
            id=str(i.id),
            name=i.name,
            description=i.description,
            examples=i.examples,
            action_type=i.action_type,
            action_config=i.action_config,
            created_at=i.created_at.isoformat(),
        )
        for i in intents
    ]


@router.delete("/{intent_id}")
async def delete_intent(
    intent_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete an intent."""
    result = await db.execute(
        select(Intent).where(
            Intent.id == intent_id,
            Intent.tenant_id == tenant.id,
        )
    )
    intent = result.scalar_one_or_none()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")

    await db.delete(intent)
    await db.flush()

    return {"status": "deleted"}


@router.post("/test", response_model=IntentTestResponse)
async def test_intent_detection(
    data: IntentTestRequest,
    tenant: Tenant = Depends(get_current_tenant),
):
    """Test intent detection with a sample message."""
    vector_store = VectorStoreService()
    try:
        result = await vector_store.detect_intent(str(tenant.id), data.message)
    finally:
        await vector_store.close()

    if not result:
        return IntentTestResponse(
            intent_name=None,
            confidence=None,
            action_type=None,
            matched_example=None,
        )

    return IntentTestResponse(
        intent_name=result["intent_name"],
        confidence=result["confidence"],
        action_type=result["action_type"],
        matched_example=result["matched_example"],
    )
