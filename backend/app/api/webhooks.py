import hashlib
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Query, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.database import get_db, async_session_factory
from app.models.tenant import Tenant, TenantStatus
from app.models.conversation import Conversation, Message, ConversationStatus, MessageRole
from app.models.guardrail import GuardrailConfig
from app.services.whatsapp import WhatsAppService
from app.services.rag import RAGService
from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.services.memory import MemoryService
from app.services.guardrail import GuardrailService
from app.services.billing import BillingService
from app.services.sales import SalesService
from app.models.upsell import UpsellOutcome

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

whatsapp_service = WhatsAppService()


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    """WhatsApp webhook verification endpoint."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def handle_whatsapp_webhook(request: Request):
    """Handle incoming WhatsApp messages."""
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not whatsapp_service.verify_webhook_signature(body, signature):
        logger.warning(
            f"Webhook signature verification failed. "
            f"Signature header present: {bool(signature)}, "
            f"Signature prefix: {signature[:20] if signature else 'EMPTY'}"
        )
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Extract message
    message = whatsapp_service.extract_message(payload)
    if not message:
        return {"status": "ok"}  # status update or non-message event

    # Process asynchronously (don't block the webhook response)
    import asyncio
    asyncio.create_task(_process_message(message))

    return {"status": "ok"}


async def _process_message(message: dict):
    """Process an incoming WhatsApp message."""
    try:
        async with async_session_factory() as db:
            phone_number_id = message["phone_number_id"]
            sender_phone = message["from"]
            text = message.get("text", "")
            logger.info(f"[PIPELINE] START processing message from {sender_phone}: {text[:50]}")

            # Find tenant by WhatsApp phone number ID
            result = await db.execute(
                select(Tenant).where(
                    Tenant.whatsapp_phone_number_id == phone_number_id,
                    Tenant.status == TenantStatus.ACTIVE,
                )
            )
            tenant = result.scalar_one_or_none()
            if not tenant:
                logger.warning(f"[PIPELINE] No active tenant for phone_number_id: {phone_number_id}")
                return
            logger.info(f"[PIPELINE] Found tenant: {tenant.name} (id={tenant.id})")

            # Mark as read
            try:
                await whatsapp_service.mark_as_read(
                    phone_number_id, tenant.whatsapp_access_token, message["message_id"]
                )
                logger.info("[PIPELINE] Marked message as read")
            except Exception as e:
                logger.error(f"[PIPELINE] Failed to mark as read: {e}")

            # Check if this is an admin command
            if sender_phone in (tenant.get_admin_phones()):
                admin_response = await _handle_admin_command(text, tenant, db)
                if admin_response:
                    await whatsapp_service.send_text_message(
                        phone_number_id, tenant.whatsapp_access_token,
                        sender_phone, admin_response,
                    )
                    logger.info("[PIPELINE] Handled admin command, done")
                    return

            # Get or create conversation session
            session_id = _get_session_id(str(tenant.id), sender_phone)
            logger.info(f"[PIPELINE] Session ID: {session_id[:16]}...")

            # Get active guardrail config
            result = await db.execute(
                select(GuardrailConfig).where(
                    GuardrailConfig.tenant_id == tenant.id,
                    GuardrailConfig.is_active.is_(True),
                )
            )
            guardrail_record = result.scalar_one_or_none()
            guardrail_config = None
            if guardrail_record:
                guardrail_config = GuardrailService.parse_yaml(guardrail_record.config_yaml)
                logger.info("[PIPELINE] Loaded guardrail config")
            else:
                logger.info("[PIPELINE] No active guardrail config")

            # Check for escalation triggers
            if guardrail_config:
                escalation = GuardrailService.check_escalation(text, guardrail_config)
                if escalation:
                    contact = escalation.get("contact", "our front desk")
                    await whatsapp_service.send_text_message(
                        phone_number_id, tenant.whatsapp_access_token,
                        sender_phone,
                        f"I'm connecting you with a team member who can help. "
                        f"Please reach out to: {contact}",
                    )
                    logger.info("[PIPELINE] Escalation triggered, done")
                    return

            # Handle upsell button responses
            if message.get("button_id") and message["button_id"].startswith("upsell_"):
                parts = message["button_id"].split("_", 2)
                if len(parts) >= 3:
                    attempt_id = parts[1]
                    action = parts[2]
                    memory_for_tracking = MemoryService()
                    sales_for_tracking = SalesService(VectorStoreService(), memory_for_tracking)
                    try:
                        outcome = (
                            UpsellOutcome.CLICKED if action == "interested"
                            else UpsellOutcome.DISMISSED
                        )
                        await sales_for_tracking.track_outcome(attempt_id, outcome, db)
                        await db.commit()
                    finally:
                        await memory_for_tracking.close()

            # Initialize services
            logger.info("[PIPELINE] Initializing services (VectorStore, LLM, Memory, Sales)...")
            vector_store = VectorStoreService()
            llm = LLMService()
            memory = MemoryService()
            guardrail_svc = GuardrailService()
            sales_svc = SalesService(vector_store, memory) if settings.sales_enabled else None
            logger.info("[PIPELINE] Services initialized")

            try:
                rag = RAGService(vector_store, llm, memory, guardrail_svc, sales=sales_svc)

                # Process through RAG pipeline
                logger.info("[PIPELINE] Starting RAG pipeline...")
                result = await rag.process_message(
                    tenant_id=str(tenant.id),
                    session_id=session_id,
                    user_message=text,
                    guardrail_config=guardrail_config,
                    db=db,
                )
                logger.info(f"[PIPELINE] RAG complete. Response length: {len(result['response'])}, tokens: {result['tokens_used']}")

                response_text = result["response"]
                upsell_context = result.get("upsell_context")

                # Send response — use interactive buttons if upsell context has products
                logger.info(f"[PIPELINE] Sending WhatsApp reply to {sender_phone}...")
                try:
                    if (upsell_context
                            and upsell_context.get("should_upsell")
                            and upsell_context.get("recommended_products")
                            and upsell_context.get("attempt_ids")):
                        product = upsell_context["recommended_products"][0]
                        attempt_id = upsell_context["attempt_ids"][0]
                        if product.get("action_url"):
                            buttons = [
                                {"id": f"upsell_{attempt_id}_interested", "title": "Tell me more"},
                                {"id": f"upsell_{attempt_id}_no_thanks", "title": "No thanks"},
                            ]
                            send_result = await whatsapp_service.send_interactive_buttons(
                                phone_number_id, tenant.whatsapp_access_token,
                                sender_phone, response_text, buttons,
                            )
                        else:
                            send_result = await whatsapp_service.send_text_message(
                                phone_number_id, tenant.whatsapp_access_token,
                                sender_phone, response_text,
                            )
                    else:
                        send_result = await whatsapp_service.send_text_message(
                            phone_number_id, tenant.whatsapp_access_token,
                            sender_phone, response_text,
                        )
                    logger.info(f"[PIPELINE] WhatsApp reply sent: {send_result}")
                except Exception:
                    logger.exception(f"[PIPELINE] FAILED to send WhatsApp reply to {sender_phone}")

                # Update upsell attempt with conversation_id and guest_phone
                if upsell_context and upsell_context.get("attempt_ids"):
                    from app.models.upsell import UpsellAttempt
                    for aid in upsell_context["attempt_ids"]:
                        attempt_result = await db.execute(
                            select(UpsellAttempt).where(UpsellAttempt.id == aid)
                        )
                        attempt = attempt_result.scalar_one_or_none()
                        if attempt:
                            attempt.guest_phone = sender_phone

                # Record usage
                await BillingService.record_usage(
                    db,
                    tenant_id=str(tenant.id),
                    messages=1,
                    tokens=result["tokens_used"],
                )
                logger.info("[PIPELINE] Usage recorded")

                # Upsert conversation record
                await _upsert_conversation(
                    db, str(tenant.id), sender_phone, session_id,
                    text, response_text,
                    result.get("intent", {}).get("intent_name") if result.get("intent") else None,
                    result["tokens_used"],
                )

                # Link upsell attempts to the conversation
                if upsell_context and upsell_context.get("attempt_ids"):
                    conv_result = await db.execute(
                        select(Conversation).where(Conversation.session_id == session_id)
                    )
                    conv = conv_result.scalar_one_or_none()
                    if conv:
                        for aid in upsell_context["attempt_ids"]:
                            attempt_result = await db.execute(
                                select(UpsellAttempt).where(UpsellAttempt.id == aid)
                            )
                            attempt = attempt_result.scalar_one_or_none()
                            if attempt:
                                attempt.conversation_id = conv.id

                await db.commit()
                logger.info("[PIPELINE] Conversation saved & committed. DONE.")

            finally:
                await vector_store.close()
                await memory.close()

    except Exception:
        logger.exception("[PIPELINE] ERROR processing WhatsApp message")


async def _handle_admin_command(text: str, tenant: Tenant, db: AsyncSession) -> str | None:
    """Handle admin commands sent via WhatsApp."""
    text = text.strip().lower()

    if text == "/usage":
        now = datetime.utcnow()
        usage = await BillingService.get_monthly_usage(
            db, str(tenant.id), now.year, now.month
        )
        overage = await BillingService.check_overage(db, tenant)
        month_name = now.strftime("%B %Y")

        from app.pricing import get_currency_symbol
        sym = get_currency_symbol(tenant.currency)
        return (
            f"Usage Report - {month_name}\n"
            f"{'─' * 25}\n"
            f"Plan: {tenant.plan.value.title()} ({_plan_price(tenant.plan, tenant.currency)}/mo)\n"
            f"Conversations: {usage['total_conversations']} / {overage['included']}\n"
            f"Remaining: {overage['remaining']}\n"
            f"Overage: {overage['overage']} ({sym}{overage['overage_cost']})\n"
            f"Messages: {usage['total_messages']}\n"
            f"Tokens used: {usage['total_tokens']:,}\n"
            f"Est. cost: {sym}{usage['total_cost']:.2f}\n\n"
            f"Dashboard: https://concierge.yourdomain.com/dashboard"
        )

    if text == "/status":
        return (
            f"Tenant: {tenant.name}\n"
            f"Status: {tenant.status.value}\n"
            f"Plan: {tenant.plan.value.title()}\n"
            f"WhatsApp: Connected\n"
        )

    if text == "/help":
        return (
            "Admin Commands:\n"
            "/usage - View monthly usage report\n"
            "/status - Check system status\n"
            "/help - Show this help message\n"
        )

    return None


def _get_session_id(tenant_id: str, phone: str) -> str:
    """Generate a deterministic session ID for tenant+phone pair."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    raw = f"{tenant_id}:{phone}:{today}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def _upsert_conversation(
    db: AsyncSession,
    tenant_id: str,
    guest_phone: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
    intent: str | None,
    tokens_used: int,
):
    """Create or update a conversation record."""
    result = await db.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            guest_phone=guest_phone,
            session_id=session_id,
            status=ConversationStatus.ACTIVE,
        )
        db.add(conversation)
        await db.flush()

        # Count as new conversation for billing
        await BillingService.record_usage(db, tenant_id, conversations=1)

    conversation.message_count += 2
    conversation.total_tokens_used += tokens_used
    conversation.last_message_at = datetime.utcnow()

    # Save messages
    user_msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=user_text,
        detected_intent=intent,
        tokens_used=0,
    )
    assistant_msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=assistant_text,
        tokens_used=tokens_used,
    )
    db.add(user_msg)
    db.add(assistant_msg)


def _plan_price(plan, currency: str = "MYR") -> str:
    from app.pricing import get_plan_price_formatted
    return get_plan_price_formatted(currency, plan.value)


@router.post("/test-pipeline")
async def test_pipeline(request: Request):
    """Diagnostic endpoint: test the full RAG pipeline without WhatsApp.
    Requires X-Admin-Key header. Returns the pipeline result or error details.
    """
    admin_key = request.headers.get("X-Admin-Key", "")
    if admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")

    body = await request.json()
    tenant_id = body.get("tenant_id")
    message = body.get("message", "Hello")
    session_id = body.get("session_id", "test-pipeline-session")

    steps = {}

    # Step 1: Find tenant
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()
            if not tenant:
                return {"error": f"Tenant {tenant_id} not found", "steps": steps}
            steps["tenant"] = {"name": tenant.name, "status": tenant.status.value}

            # Step 2: Load guardrails
            result = await db.execute(
                select(GuardrailConfig).where(
                    GuardrailConfig.tenant_id == tenant.id,
                    GuardrailConfig.is_active.is_(True),
                )
            )
            guardrail_record = result.scalar_one_or_none()
            guardrail_config = None
            if guardrail_record:
                guardrail_config = GuardrailService.parse_yaml(guardrail_record.config_yaml)
                steps["guardrails"] = "loaded"
            else:
                steps["guardrails"] = "none"

            # Step 3: Initialize services
            vector_store = VectorStoreService()
            llm = LLMService()
            memory = MemoryService()
            guardrail_svc = GuardrailService()
            sales_svc = SalesService(vector_store, memory) if settings.sales_enabled else None
            steps["services"] = "initialized"

            try:
                # Step 4: RAG pipeline
                rag = RAGService(vector_store, llm, memory, guardrail_svc, sales=sales_svc)
                result = await rag.process_message(
                    tenant_id=str(tenant.id),
                    session_id=session_id,
                    user_message=message,
                    guardrail_config=guardrail_config,
                    db=db,
                )
                steps["rag"] = {
                    "response_length": len(result["response"]),
                    "tokens_used": result["tokens_used"],
                    "intent": result.get("intent"),
                    "sources": result.get("sources", []),
                    "has_upsell": bool((result.get("upsell_context") or {}).get("should_upsell")),
                }

                await db.commit()
                steps["db_commit"] = "success"

                return {
                    "status": "success",
                    "response": result["response"][:500],
                    "steps": steps,
                }
            finally:
                await vector_store.close()
                await memory.close()

    except Exception as e:
        import traceback
        steps["error"] = str(e)
        steps["traceback"] = traceback.format_exc()
        return {"status": "error", "steps": steps}
