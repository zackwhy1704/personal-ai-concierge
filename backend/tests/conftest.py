import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.api.auth import get_current_tenant, verify_admin
from app.models.tenant import Tenant, PlanType, TenantStatus


# Use aiosqlite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_tenant(db_session):
    tenant = Tenant(
        name="Test Hotel",
        slug="test-hotel",
        api_key="pac_test12345678",
        api_key_hash="testhash",
        plan=PlanType.PROFESSIONAL,
        status=TenantStatus.ACTIVE,
        whatsapp_phone_number_id="123456789",
        whatsapp_access_token="test_token",
        admin_phone_numbers="+6591234567",
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def client(db_engine, test_tenant):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_get_tenant():
        return test_tenant

    async def override_verify_admin():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_tenant] = override_get_tenant
    app.dependency_overrides[verify_admin] = override_verify_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def mock_vector_store():
    with patch("app.services.vector_store.VectorStoreService") as mock:
        instance = mock.return_value
        instance.initialize_collections = AsyncMock()
        instance.get_embedding = AsyncMock(return_value=[0.1] * 1536)
        instance.get_embeddings_batch = AsyncMock(return_value=[[0.1] * 1536])
        instance.upsert_knowledge_chunks = AsyncMock(return_value=["point_1"])
        instance.upsert_intent_examples = AsyncMock(return_value=["point_1"])
        instance.search_knowledge = AsyncMock(return_value=[
            {"content": "Test knowledge", "title": "Test", "score": 0.9, "document_id": "doc1"}
        ])
        instance.detect_intent = AsyncMock(return_value={
            "intent_name": "room_booking",
            "confidence": 0.85,
            "action_type": "link",
            "action_config": {"url": "https://hotel.com/book"},
            "matched_example": "I want to book a room",
        })
        instance.close = AsyncMock()
        yield instance


@pytest.fixture
def mock_llm():
    with patch("app.services.llm.LLMService") as mock:
        instance = mock.return_value
        instance.generate_response = AsyncMock(return_value={
            "content": "I'd be happy to help you with your booking!",
            "tokens_used": 150,
            "input_tokens": 100,
            "output_tokens": 50,
            "stop_reason": "end_turn",
        })
        instance.summarize_conversation = AsyncMock(return_value="Guest asked about booking.")
        yield instance


@pytest.fixture
def mock_memory():
    with patch("app.services.memory.MemoryService") as mock:
        instance = mock.return_value
        instance.get_session_messages = AsyncMock(return_value=[])
        instance.get_session_summary = AsyncMock(return_value=None)
        instance.add_message = AsyncMock()
        instance.set_session_summary = AsyncMock()
        instance.close = AsyncMock()
        yield instance
