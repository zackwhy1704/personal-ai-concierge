from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "Personal AI Concierge"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/concierge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # WhatsApp Meta Cloud API
    whatsapp_api_url: str = "https://graph.facebook.com/v21.0"
    whatsapp_verify_token: str = ""
    whatsapp_api_token: str = ""
    whatsapp_app_secret: str = ""

    # Anthropic (Claude Haiku)
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_max_tokens: int = 1024

    # OpenAI Embeddings
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Qdrant
    qdrant_url: str = "https://your-cluster.qdrant.io"
    qdrant_api_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_starter_price_id: str = ""
    stripe_professional_price_id: str = ""
    stripe_enterprise_price_id: str = ""

    # Admin
    admin_api_key: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # RAG
    rag_chunk_size: int = 400
    rag_chunk_overlap: int = 50
    rag_top_k: int = 5

    # Session
    session_max_turns: int = 20
    session_timeout_minutes: int = 30
    session_summary_threshold: int = 15

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
