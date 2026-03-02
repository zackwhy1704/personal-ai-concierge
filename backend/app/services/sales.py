import json
import hashlib
import logging
import random
from typing import Optional
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.product import Product, ProductStatus
from app.models.upsell import (
    UpsellStrategy,
    UpsellAttempt,
    UpsellTriggerType,
    UpsellOutcome,
)
from app.services.vector_store import VectorStoreService
from app.services.memory import MemoryService

logger = logging.getLogger(__name__)
settings = get_settings()


class SalesService:
    """Orchestrates upsell logic: strategy matching, product recommendation, tracking."""

    def __init__(self, vector_store: VectorStoreService, memory: MemoryService):
        self.vector_store = vector_store
        self.memory = memory

    async def get_upsell_context(
        self,
        tenant_id: str,
        session_id: str,
        user_message: str,
        detected_intent: Optional[dict],
        db: AsyncSession,
    ) -> dict:
        """
        Determine what products to recommend and how.
        Returns upsell context for injection into the RAG system prompt.
        """
        if not settings.sales_enabled:
            return {"should_upsell": False}

        # Check if we've exceeded upsell limit for this session
        upsell_count = await self._get_session_upsell_count(session_id)
        if upsell_count >= settings.sales_max_upsells_per_session:
            return {"should_upsell": False}

        # Get active strategies for this tenant
        strategies = await self._get_active_strategies(tenant_id, db)
        if not strategies:
            # No strategies but check if tenant has products — use proactive search
            product_count = await db.scalar(
                select(func.count(Product.id)).where(
                    Product.tenant_id == tenant_id,
                    Product.status == ProductStatus.ACTIVE,
                )
            )
            if not product_count:
                return {"should_upsell": False}

        # Evaluate which strategies match the current context
        matched_strategies = await self.evaluate_strategies(
            tenant_id, user_message, detected_intent, db
        )

        # Select best strategy using Thompson Sampling
        selected_strategy = await self._select_strategy(matched_strategies, db)

        # Search for relevant products
        products = await self.vector_store.search_products(
            tenant_id=tenant_id,
            query=user_message,
            top_k=settings.sales_product_match_top_k,
        )

        if not products:
            return {"should_upsell": False}

        # Filter out products already shown in this session
        shown_product_ids = await self._get_shown_products(session_id)
        products = [p for p in products if p["product_id"] not in shown_product_ids]

        if not products:
            return {"should_upsell": False}

        # Get full product details from DB for the top matches
        product_details = []
        for p in products[:2]:
            result = await db.execute(
                select(Product).where(
                    Product.id == p["product_id"],
                    Product.status == ProductStatus.ACTIVE,
                )
            )
            product = result.scalar_one_or_none()
            if product:
                product_details.append({
                    "product_id": str(product.id),
                    "name": product.name,
                    "description": product.description or "",
                    "price": product.price,
                    "currency": product.currency,
                    "action_url": product.action_url,
                    "category": product.category or "",
                    "score": p["score"],
                })

        if not product_details:
            return {"should_upsell": False}

        # Determine A/B test group for this session
        ab_group = await self._get_session_ab_group(session_id, tenant_id)

        # Build the prompt injection
        upsell_prompt = self.build_upsell_prompt(
            product_details, selected_strategy, user_message
        )

        # Create UpsellAttempt records
        attempt_ids = []
        for pd in product_details[:1]:  # record for top product
            attempt = UpsellAttempt(
                tenant_id=tenant_id,
                conversation_id=None,  # will be set by webhook handler
                product_id=pd["product_id"],
                strategy_id=str(selected_strategy.id) if selected_strategy else None,
                outcome=UpsellOutcome.PRESENTED,
                trigger_context={
                    "intent": detected_intent.get("intent_name") if detected_intent else None,
                    "intent_confidence": detected_intent.get("confidence") if detected_intent else None,
                    "user_message_preview": user_message[:100],
                    "product_score": pd["score"],
                },
                guest_phone=None,  # set by webhook handler
                session_id=session_id,
                ab_test_group=ab_group,
            )
            db.add(attempt)
            await db.flush()
            attempt_ids.append(str(attempt.id))

        # Update session tracking in Redis
        await self._increment_session_upsell_count(session_id)
        await self._add_shown_products(
            session_id, [pd["product_id"] for pd in product_details[:1]]
        )
        await self._store_session_attempts(session_id, attempt_ids)

        return {
            "should_upsell": True,
            "recommended_products": product_details,
            "active_strategy": {
                "id": str(selected_strategy.id),
                "name": selected_strategy.name,
                "trigger_type": selected_strategy.trigger_type.value,
            } if selected_strategy else None,
            "upsell_prompt_injection": upsell_prompt,
            "attempt_ids": attempt_ids,
            "ab_test_group": ab_group,
        }

    async def evaluate_strategies(
        self,
        tenant_id: str,
        user_message: str,
        detected_intent: Optional[dict],
        db: AsyncSession,
    ) -> list[UpsellStrategy]:
        """Find which strategies are triggered by the current context."""
        result = await db.execute(
            select(UpsellStrategy).where(
                UpsellStrategy.tenant_id == tenant_id,
                UpsellStrategy.is_active.is_(True),
            ).order_by(UpsellStrategy.priority.desc())
        )
        strategies = result.scalars().all()
        matched = []

        message_lower = user_message.lower()

        for strategy in strategies:
            config = strategy.trigger_config or {}

            if strategy.trigger_type == UpsellTriggerType.INTENT_MATCH:
                if detected_intent:
                    target_intents = config.get("intent_names", [])
                    min_confidence = config.get("min_confidence", 0.5)
                    if (detected_intent["intent_name"] in target_intents
                            and detected_intent["confidence"] >= min_confidence):
                        matched.append(strategy)

            elif strategy.trigger_type == UpsellTriggerType.KEYWORD:
                keywords = config.get("keywords", [])
                if any(kw.lower() in message_lower for kw in keywords):
                    matched.append(strategy)

            elif strategy.trigger_type == UpsellTriggerType.CATEGORY_CONTEXT:
                # Always matches — products are filtered by category later
                matched.append(strategy)

            elif strategy.trigger_type == UpsellTriggerType.PROACTIVE:
                # Matches with a probability to avoid being too aggressive
                probability = config.get("probability", 0.3)
                if random.random() < probability:
                    matched.append(strategy)

            elif strategy.trigger_type == UpsellTriggerType.CROSS_SELL:
                # Matches if a source product was already discussed
                matched.append(strategy)

        return matched

    async def _select_strategy(
        self,
        matched: list[UpsellStrategy],
        db: AsyncSession,
    ) -> Optional[UpsellStrategy]:
        """Select the best strategy using Thompson Sampling."""
        if not matched:
            return None
        if len(matched) == 1:
            return matched[0]

        best_score = -1
        best_strategy = matched[0]

        for strategy in matched:
            # Get attempt counts for this strategy
            total = await db.scalar(
                select(func.count(UpsellAttempt.id)).where(
                    UpsellAttempt.strategy_id == strategy.id
                )
            ) or 0
            conversions = await db.scalar(
                select(func.count(UpsellAttempt.id)).where(
                    UpsellAttempt.strategy_id == strategy.id,
                    UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
                )
            ) or 0

            # Thompson Sampling: sample from Beta distribution
            alpha = conversions + 1
            beta_param = (total - conversions) + 1
            score = random.betavariate(alpha, beta_param)

            # Add priority bonus
            score += strategy.priority * 0.01

            if score > best_score:
                best_score = score
                best_strategy = strategy

        return best_strategy

    def build_upsell_prompt(
        self,
        products: list[dict],
        strategy: Optional[UpsellStrategy],
        user_message: str,
    ) -> str:
        """Build the upsell instruction text for the system prompt."""
        product_lines = []
        for i, p in enumerate(products[:2], 1):
            price_str = f" - ${p['price']}" if p.get("price") else ""
            desc = p["description"][:150] if p.get("description") else ""
            url = f"\n   Booking: {p['action_url']}" if p.get("action_url") else ""
            product_lines.append(
                f"{i}. [{p['name']}]{price_str} - {desc}{url}"
            )

        products_text = "\n".join(product_lines)

        # Use strategy's custom prompt template if available
        if strategy and strategy.prompt_template:
            approach = strategy.prompt_template
        else:
            approach = (
                "If the conversation naturally allows it, you may briefly mention "
                "one of these products/services as a helpful suggestion."
            )

        return (
            "SALES ASSISTANCE GUIDELINES:\n"
            "Based on the conversation context, the following products/services may be "
            "relevant to this customer. If it feels natural, you may mention ONE of these. "
            "Do NOT be pushy or aggressive. Only suggest if it genuinely helps the customer.\n\n"
            f"Recommended products (mention at most one, only if relevant):\n{products_text}\n\n"
            f"Suggested approach: {approach}\n\n"
            "IMPORTANT: Your primary job is to be helpful. Sales suggestions are secondary. "
            "Never sacrifice helpfulness for a sales pitch. If the customer has already "
            "declined a suggestion, do NOT bring it up again."
        )

    async def track_outcome(
        self,
        attempt_id: str,
        outcome: UpsellOutcome,
        db: AsyncSession,
        revenue: float = 0.0,
    ):
        """Update an UpsellAttempt with its outcome."""
        result = await db.execute(
            select(UpsellAttempt).where(UpsellAttempt.id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if attempt:
            attempt.outcome = outcome
            attempt.outcome_at = datetime.utcnow()
            if revenue > 0:
                attempt.revenue_attributed = revenue
            await db.flush()
            logger.info(f"Updated upsell attempt {attempt_id} outcome to {outcome.value}")

    async def detect_interest_from_response(
        self,
        user_message: str,
        pending_attempt_ids: list[str],
        db: AsyncSession,
    ):
        """Check if user's message shows interest in a previously presented product."""
        if not pending_attempt_ids:
            return

        interest_keywords = [
            kw.strip().lower()
            for kw in settings.sales_interest_keywords.split(",")
        ]
        message_lower = user_message.lower()

        if any(kw in message_lower for kw in interest_keywords):
            for attempt_id in pending_attempt_ids:
                result = await db.execute(
                    select(UpsellAttempt).where(
                        UpsellAttempt.id == attempt_id,
                        UpsellAttempt.outcome == UpsellOutcome.PRESENTED,
                    )
                )
                attempt = result.scalar_one_or_none()
                if attempt:
                    attempt.outcome = UpsellOutcome.INTEREST_SHOWN
                    attempt.outcome_at = datetime.utcnow()
                    logger.info(f"Interest detected for upsell attempt {attempt_id}")
            await db.flush()

    async def get_pending_attempts(self, session_id: str) -> list[str]:
        """Get pending upsell attempt IDs from Redis session."""
        key = f"session:{session_id}:upsell_attempts"
        raw = await self.memory.redis.get(key)
        if raw:
            return json.loads(raw)
        return []

    async def _get_active_strategies(
        self, tenant_id: str, db: AsyncSession
    ) -> list[UpsellStrategy]:
        result = await db.execute(
            select(UpsellStrategy).where(
                UpsellStrategy.tenant_id == tenant_id,
                UpsellStrategy.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def _get_session_upsell_count(self, session_id: str) -> int:
        key = f"session:{session_id}:upsell_count"
        count = await self.memory.redis.get(key)
        return int(count) if count else 0

    async def _increment_session_upsell_count(self, session_id: str):
        key = f"session:{session_id}:upsell_count"
        pipe = self.memory.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, self.memory.session_timeout)
        await pipe.execute()

    async def _get_shown_products(self, session_id: str) -> list[str]:
        key = f"session:{session_id}:upsell_products"
        raw = await self.memory.redis.get(key)
        if raw:
            return json.loads(raw)
        return []

    async def _add_shown_products(self, session_id: str, product_ids: list[str]):
        key = f"session:{session_id}:upsell_products"
        existing = await self._get_shown_products(session_id)
        existing.extend(product_ids)
        pipe = self.memory.redis.pipeline()
        pipe.set(key, json.dumps(existing))
        pipe.expire(key, self.memory.session_timeout)
        await pipe.execute()

    async def _store_session_attempts(self, session_id: str, attempt_ids: list[str]):
        key = f"session:{session_id}:upsell_attempts"
        existing = await self.get_pending_attempts(session_id)
        existing.extend(attempt_ids)
        pipe = self.memory.redis.pipeline()
        pipe.set(key, json.dumps(existing))
        pipe.expire(key, self.memory.session_timeout)
        await pipe.execute()

    async def _get_session_ab_group(self, session_id: str, tenant_id: str) -> Optional[str]:
        key = f"session:{session_id}:ab_group"
        group = await self.memory.redis.get(key)
        if group:
            return group
        # Deterministic assignment based on session_id
        hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        group = "A" if hash_val % 2 == 0 else "B"
        pipe = self.memory.redis.pipeline()
        pipe.set(key, group)
        pipe.expire(key, self.memory.session_timeout)
        await pipe.execute()
        return group
