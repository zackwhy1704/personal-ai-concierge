import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.upsell import (
    UpsellStrategy,
    UpsellAttempt,
    UpsellTriggerType,
    UpsellOutcome,
)
from app.models.conversation import Conversation, Message, MessageRole
from app.services.llm import LLMService
from app.services.sales_analytics import SalesAnalyticsService

logger = logging.getLogger(__name__)
settings = get_settings()


class LearningService:
    """Analyzes sales data and adjusts strategies for improvement."""

    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def analyze_strategy_performance(self, tenant_id: str) -> dict:
        """Analyze last 30 days of strategy performance."""
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        strategies = await SalesAnalyticsService.get_strategy_performance(
            self.db, tenant_id, start_date, end_date
        )

        if not strategies:
            return {"status": "no_data", "strategies": []}

        # Calculate overall averages
        total_attempts = sum(s["attempts"] for s in strategies)
        total_conversions = sum(s["conversions"] for s in strategies)
        avg_rate = total_conversions / total_attempts if total_attempts > 0 else 0

        for s in strategies:
            s["vs_average"] = (
                "above" if s["conversion_rate"] > avg_rate
                else "below" if s["conversion_rate"] < avg_rate
                else "equal"
            )

        return {
            "status": "analyzed",
            "period_days": 30,
            "overall_conversion_rate": avg_rate,
            "total_attempts": total_attempts,
            "total_conversions": total_conversions,
            "strategies": strategies,
        }

    async def generate_strategy_recommendations(self, tenant_id: str) -> list[dict]:
        """Use LLM to analyze patterns and suggest improvements."""
        # Get converted conversations
        converted_attempts = await self.db.execute(
            select(UpsellAttempt)
            .where(
                UpsellAttempt.tenant_id == tenant_id,
                UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
                UpsellAttempt.conversation_id.isnot(None),
            )
            .order_by(UpsellAttempt.presented_at.desc())
            .limit(10)
        )
        converted = converted_attempts.scalars().all()

        # Get failed attempts
        failed_attempts = await self.db.execute(
            select(UpsellAttempt)
            .where(
                UpsellAttempt.tenant_id == tenant_id,
                UpsellAttempt.outcome.in_([
                    UpsellOutcome.DISMISSED, UpsellOutcome.REJECTED
                ]),
                UpsellAttempt.conversation_id.isnot(None),
            )
            .order_by(UpsellAttempt.presented_at.desc())
            .limit(10)
        )
        failed = failed_attempts.scalars().all()

        if not converted and not failed:
            return [{"type": "info", "message": "Not enough data for recommendations yet."}]

        # Collect conversation excerpts
        success_contexts = []
        for attempt in converted[:5]:
            if attempt.trigger_context:
                success_contexts.append(
                    f"- Product suggested when user said: "
                    f"'{attempt.trigger_context.get('user_message_preview', 'N/A')}' "
                    f"(intent: {attempt.trigger_context.get('intent', 'none')}, "
                    f"score: {attempt.trigger_context.get('product_score', 0):.2f})"
                )

        failure_contexts = []
        for attempt in failed[:5]:
            if attempt.trigger_context:
                failure_contexts.append(
                    f"- Product suggested when user said: "
                    f"'{attempt.trigger_context.get('user_message_preview', 'N/A')}' "
                    f"(intent: {attempt.trigger_context.get('intent', 'none')}, "
                    f"score: {attempt.trigger_context.get('product_score', 0):.2f})"
                )

        success_text = "\n".join(success_contexts) if success_contexts else "No successful upsells yet."
        failure_text = "\n".join(failure_contexts) if failure_contexts else "No failed upsells recorded."

        prompt = (
            f"Analyze these sales upsell results:\n\n"
            f"SUCCESSFUL upsells (customer accepted):\n{success_text}\n\n"
            f"FAILED upsells (customer declined/ignored):\n{failure_text}\n\n"
            f"Based on these patterns, provide 3 specific recommendations to improve "
            f"the upsell strategy. Focus on:\n"
            f"1. Timing - when to suggest products\n"
            f"2. Relevance - what products to suggest based on context\n"
            f"3. Approach - how to phrase suggestions\n\n"
            f"Return each recommendation as a brief, actionable point."
        )

        try:
            response = await self.llm.generate_response(
                system_prompt="You are a sales optimization expert. Analyze upsell data and provide actionable recommendations.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            return [{"type": "llm_recommendation", "content": response["content"]}]
        except Exception as e:
            logger.exception("LLM recommendation generation failed")
            return [{"type": "error", "message": str(e)}]

    async def auto_adjust_strategy_weights(self, tenant_id: str) -> list[dict]:
        """Automatically adjust strategy priorities based on performance."""
        result = await self.db.execute(
            select(UpsellStrategy).where(
                UpsellStrategy.tenant_id == tenant_id,
                UpsellStrategy.is_active.is_(True),
            )
        )
        strategies = result.scalars().all()

        if not strategies:
            return []

        adjustments = []
        strategy_stats = []

        for strategy in strategies:
            total = await self.db.scalar(
                select(func.count(UpsellAttempt.id)).where(
                    UpsellAttempt.strategy_id == strategy.id
                )
            ) or 0
            conversions = await self.db.scalar(
                select(func.count(UpsellAttempt.id)).where(
                    UpsellAttempt.strategy_id == strategy.id,
                    UpsellAttempt.outcome == UpsellOutcome.CONVERTED,
                )
            ) or 0

            # Bayesian smoothing
            rate = (conversions + 1) / (total + 2)
            strategy_stats.append({
                "strategy": strategy,
                "total": total,
                "conversions": conversions,
                "rate": rate,
            })

        if not strategy_stats:
            return []

        avg_rate = sum(s["rate"] for s in strategy_stats) / len(strategy_stats)

        for stat in strategy_stats:
            strategy = stat["strategy"]
            old_priority = strategy.priority

            if stat["total"] < settings.sales_learning_min_attempts:
                # Not enough data — don't adjust
                adjustments.append({
                    "strategy_id": str(strategy.id),
                    "name": strategy.name,
                    "action": "skip",
                    "reason": f"Only {stat['total']} attempts (min: {settings.sales_learning_min_attempts})",
                })
                continue

            if stat["rate"] > avg_rate:
                # Above average — boost priority
                strategy.priority = min(old_priority + 1, 100)
                action = "boosted"
            elif stat["rate"] < avg_rate * 0.5:
                # Below 50% of average — decrease
                strategy.priority = max(old_priority - 1, -10)
                action = "decreased"

                # Auto-deactivate if 0 conversions after many attempts
                if stat["conversions"] == 0 and stat["total"] >= settings.sales_learning_min_attempts * 2:
                    strategy.is_active = False
                    action = "deactivated"
            else:
                action = "unchanged"

            adjustments.append({
                "strategy_id": str(strategy.id),
                "name": strategy.name,
                "action": action,
                "old_priority": old_priority,
                "new_priority": strategy.priority,
                "conversion_rate": stat["rate"],
                "attempts": stat["total"],
                "conversions": stat["conversions"],
            })

        await self.db.flush()
        return adjustments

    async def identify_cross_sell_pairs(self, tenant_id: str) -> list[dict]:
        """Find products that convert together and create cross-sell strategies."""
        patterns = await SalesAnalyticsService.get_cross_sell_patterns(
            self.db, tenant_id, limit=20
        )

        if len(patterns) < 2:
            return []

        # Find pairs with enough co-occurrences
        discoveries = []
        for i, p1 in enumerate(patterns):
            for p2 in patterns[i + 1:]:
                if p1["co_conversions"] >= 5 and p2["co_conversions"] >= 5:
                    # Check if a cross-sell strategy already exists for this pair
                    existing = await self.db.execute(
                        select(UpsellStrategy).where(
                            UpsellStrategy.tenant_id == tenant_id,
                            UpsellStrategy.trigger_type == UpsellTriggerType.CROSS_SELL,
                            UpsellStrategy.trigger_config["source_product_ids"].contains(
                                [p1["product_id"]]
                            ),
                        )
                    )
                    if not existing.scalar_one_or_none():
                        # Auto-create cross-sell strategy
                        new_strategy = UpsellStrategy(
                            tenant_id=tenant_id,
                            name=f"Cross-sell: {p1['name']} → {p2['name']}",
                            description=f"Auto-discovered: customers who buy {p1['name']} often also buy {p2['name']}",
                            trigger_type=UpsellTriggerType.CROSS_SELL,
                            trigger_config={
                                "source_product_ids": [p1["product_id"]],
                                "target_product_ids": [p2["product_id"]],
                            },
                            is_active=True,
                            priority=5,
                        )
                        self.db.add(new_strategy)

                        discoveries.append({
                            "product_a": p1["name"],
                            "product_b": p2["name"],
                            "co_conversions": min(p1["co_conversions"], p2["co_conversions"]),
                            "strategy_created": True,
                        })

        await self.db.flush()
        return discoveries

    async def run_ab_test_evaluation(self, tenant_id: str) -> list[dict]:
        """Evaluate A/B test results with statistical significance."""
        # Find strategies with A/B test groups
        result = await self.db.execute(
            select(
                UpsellAttempt.strategy_id,
                UpsellAttempt.ab_test_group,
                func.count(UpsellAttempt.id).label("attempts"),
                func.sum(
                    case(
                        (UpsellAttempt.outcome == UpsellOutcome.CONVERTED, 1),
                        else_=0,
                    )
                ).label("conversions"),
            )
            .where(
                UpsellAttempt.tenant_id == tenant_id,
                UpsellAttempt.ab_test_group.isnot(None),
            )
            .group_by(UpsellAttempt.strategy_id, UpsellAttempt.ab_test_group)
        )

        rows = result.all()

        # Group by strategy
        strategy_groups = {}
        for row in rows:
            sid = str(row.strategy_id)
            if sid not in strategy_groups:
                strategy_groups[sid] = {}
            strategy_groups[sid][row.ab_test_group] = {
                "attempts": row.attempts,
                "conversions": row.conversions,
            }

        results = []
        for strategy_id, groups in strategy_groups.items():
            if "A" not in groups or "B" not in groups:
                continue

            a = groups["A"]
            b = groups["B"]

            # Check minimum sample size
            if (a["attempts"] < settings.sales_ab_test_min_samples
                    or b["attempts"] < settings.sales_ab_test_min_samples):
                results.append({
                    "strategy_id": strategy_id,
                    "status": "insufficient_data",
                    "group_a": a,
                    "group_b": b,
                    "min_samples": settings.sales_ab_test_min_samples,
                })
                continue

            rate_a = a["conversions"] / a["attempts"] if a["attempts"] > 0 else 0
            rate_b = b["conversions"] / b["attempts"] if b["attempts"] > 0 else 0

            # Simple chi-squared approximation
            total = a["attempts"] + b["attempts"]
            total_conv = a["conversions"] + b["conversions"]
            expected_rate = total_conv / total if total > 0 else 0

            if expected_rate == 0 or expected_rate == 1:
                significance = "not_significant"
            else:
                # Chi-squared statistic
                e_a_conv = a["attempts"] * expected_rate
                e_a_noconv = a["attempts"] * (1 - expected_rate)
                e_b_conv = b["attempts"] * expected_rate
                e_b_noconv = b["attempts"] * (1 - expected_rate)

                chi2 = 0
                if e_a_conv > 0:
                    chi2 += (a["conversions"] - e_a_conv) ** 2 / e_a_conv
                if e_a_noconv > 0:
                    chi2 += ((a["attempts"] - a["conversions"]) - e_a_noconv) ** 2 / e_a_noconv
                if e_b_conv > 0:
                    chi2 += (b["conversions"] - e_b_conv) ** 2 / e_b_conv
                if e_b_noconv > 0:
                    chi2 += ((b["attempts"] - b["conversions"]) - e_b_noconv) ** 2 / e_b_noconv

                significance = "significant" if chi2 > 3.841 else "not_significant"  # p < 0.05

            winner = None
            if significance == "significant":
                winner = "A" if rate_a > rate_b else "B"
                # Auto-promote winner
                loser_group = "B" if winner == "A" else "A"
                strategy_result = await self.db.execute(
                    select(UpsellStrategy).where(UpsellStrategy.id == strategy_id)
                )
                strategy = strategy_result.scalar_one_or_none()
                if strategy:
                    strategy.ab_test_group = winner  # lock to winner
                    await self.db.flush()

            results.append({
                "strategy_id": strategy_id,
                "status": significance,
                "winner": winner,
                "group_a": {**a, "conversion_rate": rate_a},
                "group_b": {**b, "conversion_rate": rate_b},
            })

        return results

    async def run_daily_learning(self, tenant_id: str) -> dict:
        """Orchestrate all learning tasks for a tenant."""
        yesterday = date.today() - timedelta(days=1)

        # Step 1: Aggregate daily metrics
        await SalesAnalyticsService.aggregate_daily_metrics(
            self.db, tenant_id, yesterday
        )

        # Step 2: Auto-adjust strategy weights
        adjustments = await self.auto_adjust_strategy_weights(tenant_id)

        # Step 3: Discover cross-sell patterns
        cross_sells = await self.identify_cross_sell_pairs(tenant_id)

        # Step 4: Evaluate A/B tests
        ab_results = await self.run_ab_test_evaluation(tenant_id)

        return {
            "date": yesterday.isoformat(),
            "strategy_adjustments": len(adjustments),
            "cross_sell_discoveries": len(cross_sells),
            "ab_tests_evaluated": len(ab_results),
        }
