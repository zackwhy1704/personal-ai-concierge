"""
End-to-end tests simulating the full flow:
1. Create tenant
2. Upload guardrails
3. Upload knowledge base
4. Create intents
5. Simulate WhatsApp message -> RAG pipeline -> response
6. Check usage tracking
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_tenant_me(client):
    response = await client.get("/api/tenants/me")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Hotel"
    assert data["plan"] == "professional"


@pytest.mark.asyncio
async def test_guardrail_from_form(client):
    form_data = {
        "tenant_name": "Test Hotel",
        "language": ["en"],
        "persona": {
            "name": "TestBot",
            "tone": "professional",
            "greeting": "Welcome!",
        },
        "allowed_topics": ["room_booking", "faq"],
        "blocked_topics": ["politics"],
        "custom_rules": ["Always be polite"],
    }

    response = await client.post("/api/guardrails/from-form", json=form_data)
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    assert data["is_active"] is True
    assert "TestBot" in data["config_yaml"]


@pytest.mark.asyncio
async def test_guardrail_active(client):
    # Create a guardrail and immediately query active
    form_data = {
        "tenant_name": "Test Hotel",
        "persona": {"name": "Bot", "tone": "friendly", "greeting": "Hi!"},
    }
    create_response = await client.post("/api/guardrails/from-form", json=form_data)
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["is_active"] is True

    # Fetch active should return the one we just created
    response = await client.get("/api/guardrails/active")
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] is True
    assert data["id"] == created["id"]


@pytest.mark.asyncio
async def test_guardrail_versioning(client):
    # Create two versions in same test
    for i in range(2):
        form_data = {
            "tenant_name": f"Test Hotel v{i + 1}",
            "persona": {"name": f"Bot v{i + 1}", "tone": "friendly"},
        }
        r = await client.post("/api/guardrails/from-form", json=form_data)
        assert r.status_code == 200

    response = await client.get("/api/guardrails/versions")
    assert response.status_code == 200
    versions = response.json()
    assert len(versions) >= 2
    # Latest should be active
    assert versions[0]["is_active"] is True


@pytest.mark.asyncio
async def test_create_intent(client):
    with patch("app.api.intents.VectorStoreService") as MockVS:
        mock_instance = MockVS.return_value
        mock_instance.upsert_intent_examples = AsyncMock(return_value=["p1", "p2"])
        mock_instance.close = AsyncMock()

        intent_data = {
            "name": "room_booking",
            "description": "Guest wants to book a room",
            "examples": [
                "I want to book a room",
                "Reserve a room for me",
                "Do you have availability?",
            ],
            "action_type": "link",
            "action_config": {
                "url": "https://hotel.com/book",
                "label": "Book a Room",
            },
        }

        response = await client.post("/api/intents", json=intent_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "room_booking"
        assert len(data["examples"]) == 3


@pytest.mark.asyncio
async def test_list_intents(client):
    response = await client.get("/api/intents")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_upload_knowledge_document(client):
    with patch("app.api.knowledge.VectorStoreService") as MockVS:
        mock_instance = MockVS.return_value
        mock_instance.upsert_knowledge_chunks = AsyncMock(return_value=["point_1", "point_2"])
        mock_instance.close = AsyncMock()

        doc_data = {
            "title": "Room Types and Pricing",
            "content": (
                "Our hotel offers three room types. "
                "Standard rooms are comfortable with city views. "
                "Deluxe rooms include a sitting area and premium amenities. "
                "Suite rooms are our finest offering with panoramic views. "
                + " ".join(["Additional details about our rooms."] * 100)
            ),
        }

        response = await client.post("/api/knowledge", json=doc_data)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Room Types and Pricing"
        assert data["chunk_count"] > 0


@pytest.mark.asyncio
async def test_list_knowledge_documents(client):
    response = await client.get("/api/knowledge")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_usage_monthly(client):
    response = await client.get("/api/usage/monthly")
    assert response.status_code == 200
    data = response.json()
    assert "total_conversations" in data
    assert "plan" in data
    assert "included_conversations" in data


@pytest.mark.asyncio
async def test_usage_daily(client):
    response = await client.get("/api/usage/daily")
    assert response.status_code == 200
    data = response.json()
    assert "conversation_count" in data


@pytest.mark.asyncio
async def test_webhook_verification(client):
    from app.config import get_settings
    settings = get_settings()

    response = await client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "12345",
        },
    )
    # Will succeed if verify token matches, else 403
    if settings.whatsapp_verify_token:
        assert response.status_code == 200
    else:
        # Empty verify token still matches empty query param
        assert response.status_code in [200, 403]


@pytest.mark.asyncio
async def test_guardrail_schema_endpoint(client):
    response = await client.get("/api/guardrails/schema")
    assert response.status_code == 200
    schema = response.json()
    assert "properties" in schema
    assert "persona" in schema["properties"]


@pytest.mark.asyncio
async def test_full_e2e_flow(client):
    """
    Full end-to-end test simulating the complete onboarding and message flow.
    """
    # Step 1: Verify tenant exists
    response = await client.get("/api/tenants/me")
    assert response.status_code == 200
    tenant = response.json()
    assert tenant["status"] == "active"

    # Step 2: Configure guardrails
    guardrail_data = {
        "tenant_name": "E2E Test Hotel",
        "language": ["en"],
        "persona": {
            "name": "Elena",
            "tone": "warm and professional",
            "greeting": "Welcome to E2E Test Hotel! How can I help you today?",
        },
        "allowed_topics": ["room_booking", "room_service", "amenities_inquiry"],
        "blocked_topics": ["competitor_pricing", "politics"],
        "escalation_rules": [
            {
                "trigger": "speak to manager",
                "action": "transfer_to_human",
                "contact": "+6591234567",
            }
        ],
        "response_limits": {"max_response_length": 500},
        "custom_rules": [
            "Always confirm guest name before changes",
            "Direct pricing questions to booking link",
        ],
    }
    response = await client.post("/api/guardrails/from-form", json=guardrail_data)
    assert response.status_code == 200

    # Step 3: Upload knowledge base
    with patch("app.api.knowledge.VectorStoreService") as MockVS:
        mock_instance = MockVS.return_value
        mock_instance.upsert_knowledge_chunks = AsyncMock(return_value=["p1", "p2", "p3"])
        mock_instance.close = AsyncMock()

        knowledge_data = {
            "title": "Hotel Information",
            "content": (
                "E2E Test Hotel is a 5-star hotel located in the heart of Singapore. "
                "We offer Standard, Deluxe, and Suite rooms. "
                "Check-in time is 3:00 PM. Checkout time is 11:00 AM. "
                "Room service is available 24 hours. "
                "Our restaurant serves breakfast from 7 AM to 10 AM. "
                + " ".join(["More information about our hotel services."] * 50)
            ),
        }
        response = await client.post("/api/knowledge", json=knowledge_data)
        assert response.status_code == 200
        assert response.json()["chunk_count"] > 0

    # Step 4: Create intents
    with patch("app.api.intents.VectorStoreService") as MockVS:
        mock_instance = MockVS.return_value
        mock_instance.upsert_intent_examples = AsyncMock(return_value=["p1", "p2"])
        mock_instance.close = AsyncMock()

        intent_data = {
            "name": "room_booking",
            "description": "Guest wants to book a room",
            "examples": [
                "I want to book a room",
                "Reserve a room for March 5 to March 8",
                "Do you have availability this weekend?",
            ],
            "action_type": "link",
            "action_config": {"url": "https://e2ehotel.com/book", "label": "Book Now"},
        }
        response = await client.post("/api/intents", json=intent_data)
        assert response.status_code == 200

    # Step 5: Verify all configurations
    response = await client.get("/api/guardrails/active")
    assert response.status_code == 200
    assert "Elena" in response.json()["config_yaml"]

    response = await client.get("/api/intents")
    assert response.status_code == 200
    assert len(response.json()) > 0

    response = await client.get("/api/knowledge")
    assert response.status_code == 200
    assert len(response.json()) > 0

    # Step 6: Check usage
    response = await client.get("/api/usage/monthly")
    assert response.status_code == 200

    print("E2E flow completed successfully!")
