import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.upsell import UpsellStrategy, UpsellTriggerType
from app.api.auth import get_current_tenant
from app.services.vector_store import VectorStoreService
from app.services.memory import MemoryService
from app.services.sales import SalesService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upsell/strategies", tags=["upsell-strategies"])


class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: UpsellTriggerType
    trigger_config: dict = {}
    prompt_template: Optional[str] = None
    max_attempts_per_session: int = 2
    priority: int = 0
    ab_test_group: Optional[str] = None


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[UpsellTriggerType] = None
    trigger_config: Optional[dict] = None
    prompt_template: Optional[str] = None
    max_attempts_per_session: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    ab_test_group: Optional[str] = None


class StrategyResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger_type: str
    trigger_config: dict
    prompt_template: Optional[str]
    max_attempts_per_session: int
    priority: int
    is_active: bool
    ab_test_group: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class StrategyTestRequest(BaseModel):
    message: str
    intent_name: Optional[str] = None
    intent_confidence: float = 0.0


def _strategy_response(s: UpsellStrategy) -> StrategyResponse:
    return StrategyResponse(
        id=str(s.id),
        name=s.name,
        description=s.description,
        trigger_type=s.trigger_type.value,
        trigger_config=s.trigger_config or {},
        prompt_template=s.prompt_template,
        max_attempts_per_session=s.max_attempts_per_session,
        priority=s.priority,
        is_active=s.is_active,
        ab_test_group=s.ab_test_group,
        created_at=s.created_at.isoformat(),
    )


@router.post("", response_model=StrategyResponse)
async def create_strategy(
    data: StrategyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new upsell strategy."""
    strategy = UpsellStrategy(
        tenant_id=tenant.id,
        name=data.name,
        description=data.description,
        trigger_type=data.trigger_type,
        trigger_config=data.trigger_config,
        prompt_template=data.prompt_template,
        max_attempts_per_session=data.max_attempts_per_session,
        priority=data.priority,
        ab_test_group=data.ab_test_group,
    )
    db.add(strategy)
    await db.flush()
    return _strategy_response(strategy)


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    active_only: bool = False,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List upsell strategies."""
    query = select(UpsellStrategy).where(UpsellStrategy.tenant_id == tenant.id)
    if active_only:
        query = query.where(UpsellStrategy.is_active.is_(True))
    query = query.order_by(UpsellStrategy.priority.desc(), UpsellStrategy.created_at)

    result = await db.execute(query)
    strategies = result.scalars().all()
    return [_strategy_response(s) for s in strategies]


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: str,
    data: StrategyUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a strategy."""
    result = await db.execute(
        select(UpsellStrategy).where(
            UpsellStrategy.id == strategy_id,
            UpsellStrategy.tenant_id == tenant.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(strategy, field, value)
    strategy.updated_at = datetime.utcnow()
    await db.flush()

    return _strategy_response(strategy)


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a strategy."""
    result = await db.execute(
        select(UpsellStrategy).where(
            UpsellStrategy.id == strategy_id,
            UpsellStrategy.tenant_id == tenant.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    await db.delete(strategy)
    await db.flush()
    return {"status": "deleted"}


@router.post("/{strategy_id}/toggle")
async def toggle_strategy(
    strategy_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a strategy's active status."""
    result = await db.execute(
        select(UpsellStrategy).where(
            UpsellStrategy.id == strategy_id,
            UpsellStrategy.tenant_id == tenant.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    strategy.is_active = not strategy.is_active
    strategy.updated_at = datetime.utcnow()
    await db.flush()

    return {"status": "toggled", "is_active": strategy.is_active}


@router.post("/test")
async def test_strategies(
    data: StrategyTestRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Test which strategies would fire for a given message."""
    detected_intent = None
    if data.intent_name:
        detected_intent = {
            "intent_name": data.intent_name,
            "confidence": data.intent_confidence,
        }

    vector_store = VectorStoreService()
    memory = MemoryService()
    sales_svc = SalesService(vector_store, memory)
    try:
        matched = await sales_svc.evaluate_strategies(
            str(tenant.id), data.message, detected_intent, db
        )
        return {
            "matched_strategies": [
                {
                    "id": str(s.id),
                    "name": s.name,
                    "trigger_type": s.trigger_type.value,
                    "priority": s.priority,
                }
                for s in matched
            ]
        }
    finally:
        await vector_store.close()
        await memory.close()
