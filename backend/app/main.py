import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.database import init_db
from app.services.vector_store import VectorStoreService
from app.api import webhooks, tenants, guardrails, usage, intents, knowledge, billing

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
app.include_router(webhooks.router)
app.include_router(tenants.router)
app.include_router(guardrails.router)
app.include_router(usage.router)
app.include_router(intents.router)
app.include_router(knowledge.router)
app.include_router(billing.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.app_name}
