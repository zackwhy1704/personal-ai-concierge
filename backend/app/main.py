import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import get_settings
from app.db.database import init_db
from app.services.vector_store import VectorStoreService
from app.api import webhooks, tenants, guardrails, usage, intents, knowledge, billing, auth
from app.api import products, upsell_strategies, sales_analytics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Personal AI Concierge...")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception:
        logger.exception("Database init failed - will retry on first request")

    try:
        vector_store = VectorStoreService()
        await vector_store.initialize_collections()
        await vector_store.close()
        logger.info("Vector store collections initialized")
    except Exception:
        logger.exception("Vector store init failed - will retry on first request")

    yield

    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Personal AI Concierge",
    description="Multi-tenant WhatsApp AI Concierge Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(tenants.router)
app.include_router(guardrails.router)
app.include_router(usage.router)
app.include_router(intents.router)
app.include_router(knowledge.router)
app.include_router(billing.router)
app.include_router(products.router)
app.include_router(upsell_strategies.router)
app.include_router(sales_analytics.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}


@app.get("/health/services")
async def service_health_check():
    """Check connectivity to all external services."""
    results = {}

    # Check OpenAI API key format
    openai_key = settings.openai_api_key
    results["openai_key"] = {
        "set": bool(openai_key),
        "length": len(openai_key),
        "has_whitespace": openai_key != openai_key.strip() if openai_key else False,
        "prefix": openai_key[:8] + "..." if len(openai_key) > 8 else "too_short",
    }

    # Check Qdrant
    try:
        from app.services.vector_store import VectorStoreService
        vs = VectorStoreService()
        collections = await vs.client.get_collections()
        results["qdrant"] = {
            "status": "connected",
            "collections": [c.name for c in collections.collections],
        }
        await vs.close()
    except Exception as e:
        results["qdrant"] = {"status": "error", "error": str(e)}

    # Check DB
    try:
        from app.db.database import async_session_factory
        async with async_session_factory() as session:
            await session.execute(select(1))
        results["database"] = {"status": "connected"}
    except Exception as e:
        results["database"] = {"status": "error", "error": str(e)}

    # Check Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        results["redis"] = {"status": "connected", "url_prefix": settings.redis_url[:20] + "..."}
        await r.aclose()
    except Exception as e:
        results["redis"] = {"status": "error", "error": str(e), "url_prefix": settings.redis_url[:20] + "..." if settings.redis_url else "NOT_SET"}

    # Check other keys
    results["anthropic_key_set"] = bool(settings.anthropic_api_key)
    results["whatsapp_verify_token"] = settings.whatsapp_verify_token[:10] + "..." if settings.whatsapp_verify_token else "NOT_SET"
    app_secret = settings.whatsapp_app_secret
    results["whatsapp_app_secret"] = {
        "set": bool(app_secret),
        "length": len(app_secret) if app_secret else 0,
        "has_whitespace": app_secret != app_secret.strip() if app_secret else False,
        "prefix": app_secret[:4] + "..." if app_secret and len(app_secret) > 4 else "NOT_SET",
    }

    return results
