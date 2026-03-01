import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.tenant import Tenant
from app.models.guardrail import GuardrailConfig
from app.api.auth import get_current_tenant
from app.services.guardrail import GuardrailService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])
guardrail_service = GuardrailService()


class GuardrailFormData(BaseModel):
    """Web form data that gets converted to YAML."""

    tenant_name: str
    language: list[str] = ["en"]
    persona: dict = {"name": "AI Concierge", "tone": "professional and helpful", "greeting": ""}
    allowed_topics: list[str] = []
    blocked_topics: list[str] = []
    escalation_rules: list[dict] = []
    response_limits: dict = {
        "max_response_length": 500,
        "max_conversation_turns": 50,
        "session_timeout_minutes": 30,
    }
    data_handling: dict = {
        "collect_personal_data": False,
        "store_conversation_history": True,
        "retention_days": 90,
    }
    custom_rules: list[str] = []


class GuardrailYAMLUpload(BaseModel):
    yaml_content: str


class GuardrailResponse(BaseModel):
    id: str
    version: int
    is_active: bool
    config_yaml: str
    created_at: str


@router.post("/from-form", response_model=GuardrailResponse)
async def create_guardrail_from_form(
    form_data: GuardrailFormData,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create guardrail config from web form data (converts to YAML)."""
    yaml_content = guardrail_service.form_data_to_yaml(form_data.model_dump())

    # Validate
    config = guardrail_service.parse_yaml(yaml_content)
    errors = guardrail_service.validate_config(config)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    # Deactivate previous configs
    result = await db.execute(
        select(GuardrailConfig).where(
            GuardrailConfig.tenant_id == tenant.id,
            GuardrailConfig.is_active.is_(True),
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    # Get next version number
    result = await db.execute(
        select(GuardrailConfig)
        .where(GuardrailConfig.tenant_id == tenant.id)
        .order_by(GuardrailConfig.version.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    guardrail = GuardrailConfig(
        tenant_id=tenant.id,
        config_yaml=yaml_content,
        version=next_version,
        is_active=True,
    )
    db.add(guardrail)
    await db.flush()

    return GuardrailResponse(
        id=str(guardrail.id),
        version=guardrail.version,
        is_active=guardrail.is_active,
        config_yaml=guardrail.config_yaml,
        created_at=guardrail.created_at.isoformat(),
    )


@router.post("/from-yaml", response_model=GuardrailResponse)
async def create_guardrail_from_yaml(
    data: GuardrailYAMLUpload,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create guardrail config from raw YAML upload."""
    config = guardrail_service.parse_yaml(data.yaml_content)
    errors = guardrail_service.validate_config(config)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    # Deactivate previous
    result = await db.execute(
        select(GuardrailConfig).where(
            GuardrailConfig.tenant_id == tenant.id,
            GuardrailConfig.is_active.is_(True),
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    result = await db.execute(
        select(GuardrailConfig)
        .where(GuardrailConfig.tenant_id == tenant.id)
        .order_by(GuardrailConfig.version.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    guardrail = GuardrailConfig(
        tenant_id=tenant.id,
        config_yaml=data.yaml_content,
        version=next_version,
        is_active=True,
    )
    db.add(guardrail)
    await db.flush()

    return GuardrailResponse(
        id=str(guardrail.id),
        version=guardrail.version,
        is_active=guardrail.is_active,
        config_yaml=guardrail.config_yaml,
        created_at=guardrail.created_at.isoformat(),
    )


@router.get("/active", response_model=GuardrailResponse)
async def get_active_guardrail(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get the active guardrail config for the current tenant."""
    result = await db.execute(
        select(GuardrailConfig).where(
            GuardrailConfig.tenant_id == tenant.id,
            GuardrailConfig.is_active.is_(True),
        )
    )
    guardrail = result.scalar_one_or_none()
    if not guardrail:
        raise HTTPException(status_code=404, detail="No active guardrail config found")

    return GuardrailResponse(
        id=str(guardrail.id),
        version=guardrail.version,
        is_active=guardrail.is_active,
        config_yaml=guardrail.config_yaml,
        created_at=guardrail.created_at.isoformat(),
    )


@router.get("/versions", response_model=list[GuardrailResponse])
async def list_guardrail_versions(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all guardrail config versions for the current tenant."""
    result = await db.execute(
        select(GuardrailConfig)
        .where(GuardrailConfig.tenant_id == tenant.id)
        .order_by(GuardrailConfig.version.desc())
    )
    configs = result.scalars().all()
    return [
        GuardrailResponse(
            id=str(c.id),
            version=c.version,
            is_active=c.is_active,
            config_yaml=c.config_yaml,
            created_at=c.created_at.isoformat(),
        )
        for c in configs
    ]


@router.get("/schema")
async def get_guardrail_schema():
    """Return the JSON schema for the guardrail form data."""
    from app.services.guardrail import GUARDRAIL_SCHEMA
    return GUARDRAIL_SCHEMA
