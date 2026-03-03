"""
Centralized pricing configuration for all supported currencies.

Single source of truth for plan prices, overage rates, currency symbols,
and Stripe price ID mappings.
"""
from app.config import get_settings

CURRENCY_CONFIG = {
    "MYR": {
        "symbol": "RM",
        "plans": {
            "starter":      {"price": 780,  "overage_rate": 0.65},
            "professional": {"price": 2800, "overage_rate": 0.45},
            "enterprise":   {"price": 6800, "overage_rate": 0.30},
        },
        "stripe_price_keys": {
            "starter": "stripe_starter_price_id",
            "professional": "stripe_professional_price_id",
            "enterprise": "stripe_enterprise_price_id",
        },
    },
    "SGD": {
        "symbol": "S$",
        "plans": {
            "starter":      {"price": 260,  "overage_rate": 0.22},
            "professional": {"price": 930,  "overage_rate": 0.15},
            "enterprise":   {"price": 2260, "overage_rate": 0.10},
        },
        "stripe_price_keys": {
            "starter": "stripe_starter_price_id_sgd",
            "professional": "stripe_professional_price_id_sgd",
            "enterprise": "stripe_enterprise_price_id_sgd",
        },
    },
}

SUPPORTED_CURRENCIES = list(CURRENCY_CONFIG.keys())


def get_currency_symbol(currency: str) -> str:
    """Get display symbol for a currency code (e.g. 'MYR' -> 'RM')."""
    return CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])["symbol"]


def get_plan_price(currency: str, plan: str) -> int:
    """Get plan price for a currency (e.g. 'SGD', 'starter' -> 260)."""
    cfg = CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])
    return cfg["plans"].get(plan, cfg["plans"]["starter"])["price"]


def get_overage_rate(currency: str, plan: str) -> float:
    """Get overage rate per conversation for a currency + plan."""
    cfg = CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])
    return cfg["plans"].get(plan, cfg["plans"]["starter"])["overage_rate"]


def get_plan_price_formatted(currency: str, plan: str) -> str:
    """Get formatted price string (e.g. 'RM780', 'S$2,260')."""
    symbol = get_currency_symbol(currency)
    price = get_plan_price(currency, plan)
    return f"{symbol}{price:,}"


def get_plan_prices_dict(currency: str) -> dict:
    """Get {PlanType: price} dict for a currency. Used in billing notifications."""
    from app.models.tenant import PlanType
    cfg = CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])
    return {PlanType(plan): info["price"] for plan, info in cfg["plans"].items()}


def get_stripe_price_id(currency: str, plan: str) -> str:
    """Get the Stripe price ID for a currency + plan from settings."""
    settings = get_settings()
    cfg = CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])
    key = cfg["stripe_price_keys"].get(plan, "")
    return getattr(settings, key, "") if key else ""


def get_all_price_to_plan() -> dict:
    """Build reverse map: stripe_price_id -> PlanType across all currencies."""
    from app.models.tenant import PlanType
    settings = get_settings()
    result = {}
    for currency_cfg in CURRENCY_CONFIG.values():
        for plan_str, settings_key in currency_cfg["stripe_price_keys"].items():
            price_id = getattr(settings, settings_key, "")
            if price_id:
                result[price_id] = PlanType(plan_str)
    return result


def get_plans_for_currency(currency: str) -> list[dict]:
    """Get plan list for API response."""
    from app.models.tenant import PlanType
    cfg = CURRENCY_CONFIG.get(currency, CURRENCY_CONFIG["MYR"])
    conversations = {
        "starter": 500,
        "professional": 2000,
        "enterprise": 10000,
    }
    return [
        {
            "id": plan,
            "name": plan.title(),
            "price": info["price"],
            "conversations": conversations[plan],
            "overage_rate": info["overage_rate"],
        }
        for plan, info in cfg["plans"].items()
    ]
