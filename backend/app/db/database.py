from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    # Import all models so Base.metadata knows about every table
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # One-time fix: make conversation_id nullable in upsell_attempts
        # (column was created NOT NULL but needs to be nullable since
        # upsell attempts are created before the conversation record exists)
        from sqlalchemy import text
        try:
            await conn.execute(text(
                "ALTER TABLE upsell_attempts ALTER COLUMN conversation_id DROP NOT NULL"
            ))
        except Exception:
            pass  # column may already be nullable or table may not exist yet

        # Add currency column to tenants (multi-currency support)
        try:
            await conn.execute(text(
                "ALTER TABLE tenants ADD COLUMN currency VARCHAR(3) NOT NULL DEFAULT 'MYR'"
            ))
        except Exception:
            pass  # column already exists

        # Create promo_codes table if not exists (promo code free trial)
        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    code VARCHAR(50) UNIQUE NOT NULL,
                    description VARCHAR(255),
                    trial_days INTEGER NOT NULL DEFAULT 30,
                    max_redemptions INTEGER,
                    times_redeemed INTEGER NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
        except Exception:
            pass  # table already exists
