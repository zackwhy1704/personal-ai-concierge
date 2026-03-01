import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from app.services.rag import RAGService, chunk_text
from app.services.guardrail import GuardrailService


class TestChunkText:
    def test_basic_chunking(self):
        text = " ".join([f"word{i}" for i in range(100)])
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        assert len(chunks) > 1
        # First chunk should have ~20 words
        assert len(chunks[0].split()) == 20

    def test_empty_text(self):
        assert chunk_text("") == []

    def test_short_text(self):
        chunks = chunk_text("Hello world", chunk_size=400)
        assert len(chunks) == 1
        assert chunks[0] == "Hello world"

    def test_overlap(self):
        text = " ".join([f"word{i}" for i in range(40)])
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        # Words at end of chunk 1 should appear at start of chunk 2
        chunk1_words = chunks[0].split()
        chunk2_words = chunks[1].split()
        overlap_words = chunk1_words[-5:]
        assert overlap_words == chunk2_words[:5]


class TestRAGService:
    @pytest_asyncio.fixture
    async def rag_service(self):
        vector_store = AsyncMock()
        llm = AsyncMock()
        memory = AsyncMock()
        guardrail = GuardrailService()

        vector_store.detect_intent = AsyncMock(return_value={
            "intent_name": "room_booking",
            "confidence": 0.85,
            "action_type": "link",
            "action_config": {"url": "https://hotel.com/book", "label": "Book now"},
            "matched_example": "I want to book a room",
        })
        vector_store.search_knowledge = AsyncMock(return_value=[
            {"content": "We have Standard, Deluxe, and Suite rooms.", "title": "Room Types", "score": 0.9},
            {"content": "Check-in at 3PM, checkout at 11AM.", "title": "Policies", "score": 0.7},
        ])
        llm.generate_response = AsyncMock(return_value={
            "content": "We offer Standard, Deluxe, and Suite rooms. Would you like to make a booking?",
            "tokens_used": 200,
            "input_tokens": 150,
            "output_tokens": 50,
            "stop_reason": "end_turn",
        })
        memory.get_session_messages = AsyncMock(return_value=[])
        memory.get_session_summary = AsyncMock(return_value=None)
        memory.add_message = AsyncMock()

        return RAGService(vector_store, llm, memory, guardrail)

    @pytest.mark.asyncio
    async def test_process_message_basic(self, rag_service):
        result = await rag_service.process_message(
            tenant_id="tenant-123",
            session_id="session-456",
            user_message="What rooms do you have?",
        )

        assert "response" in result
        assert "intent" in result
        assert "tokens_used" in result
        assert result["tokens_used"] == 200
        assert result["intent"]["intent_name"] == "room_booking"

    @pytest.mark.asyncio
    async def test_process_message_with_guardrails(self, rag_service):
        guardrail_config = {
            "persona": {"name": "Sofia", "tone": "warm", "greeting": "Welcome!"},
            "allowed_topics": ["room_booking"],
            "blocked_topics": ["competitor_pricing"],
            "response_limits": {"max_response_length": 500},
            "custom_rules": ["Always be polite"],
        }

        result = await rag_service.process_message(
            tenant_id="tenant-123",
            session_id="session-456",
            user_message="I want to book a room",
            guardrail_config=guardrail_config,
        )

        assert "response" in result
        # Should include intent action link
        assert "Book now" in result["response"] or "hotel.com/book" in result["response"]

    @pytest.mark.asyncio
    async def test_process_message_stores_memory(self, rag_service):
        await rag_service.process_message(
            tenant_id="tenant-123",
            session_id="session-456",
            user_message="Hello",
        )

        # Should store both user and assistant messages
        assert rag_service.memory.add_message.call_count == 2


class TestRAGSystemPromptBuilding:
    def test_build_system_prompt_with_guardrails(self):
        vs = AsyncMock()
        llm = AsyncMock()
        mem = AsyncMock()
        gs = GuardrailService()
        rag = RAGService(vs, llm, mem, gs)

        prompt = rag._build_system_prompt(
            guardrail_config={
                "persona": {"name": "Sofia", "tone": "warm"},
                "allowed_topics": ["room_booking", "faq"],
                "blocked_topics": ["politics"],
                "custom_rules": ["Never quote prices"],
            },
            knowledge_chunks=[
                {"content": "Check-in is at 3PM", "title": "Policies"},
            ],
            session_summary="Guest asked about rooms.",
            intent={"intent_name": "room_booking", "confidence": 0.8},
        )

        assert "Sofia" in prompt
        assert "warm" in prompt
        assert "room_booking" in prompt
        assert "politics" in prompt
        assert "Never quote prices" in prompt
        assert "Check-in is at 3PM" in prompt
        assert "Guest asked about rooms" in prompt

    def test_build_system_prompt_without_guardrails(self):
        vs = AsyncMock()
        llm = AsyncMock()
        mem = AsyncMock()
        gs = GuardrailService()
        rag = RAGService(vs, llm, mem, gs)

        prompt = rag._build_system_prompt(
            guardrail_config=None,
            knowledge_chunks=[],
            session_summary=None,
            intent=None,
        )

        assert "helpful AI hotel concierge" in prompt
