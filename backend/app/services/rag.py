import logging
from typing import Optional
import yaml

from app.services.vector_store import VectorStoreService
from app.services.llm import LLMService
from app.services.memory import MemoryService
from app.services.guardrail import GuardrailService
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RAGService:
    """
    Core RAG (Retrieval Augmented Generation) pipeline.
    Orchestrates: intent detection → context retrieval → LLM generation → guardrail check.
    """

    def __init__(
        self,
        vector_store: VectorStoreService,
        llm: LLMService,
        memory: MemoryService,
        guardrail: GuardrailService,
    ):
        self.vector_store = vector_store
        self.llm = llm
        self.memory = memory
        self.guardrail = guardrail

    async def process_message(
        self,
        tenant_id: str,
        session_id: str,
        user_message: str,
        guardrail_config: Optional[dict] = None,
    ) -> dict:
        """
        Full RAG pipeline for processing a user message.

        Returns: {
            "response": str,
            "intent": Optional[dict],
            "tokens_used": int,
            "sources": list[str],
        }
        """
        # Step 1: Detect intent
        intent = await self.vector_store.detect_intent(tenant_id, user_message)

        # Step 2: Retrieve relevant knowledge
        knowledge_chunks = await self.vector_store.search_knowledge(
            tenant_id, user_message, top_k=settings.rag_top_k
        )

        # Step 3: Get session memory
        session_messages = await self.memory.get_session_messages(session_id)
        session_summary = await self.memory.get_session_summary(session_id)

        # Step 4: Build system prompt
        system_prompt = self._build_system_prompt(
            guardrail_config=guardrail_config,
            knowledge_chunks=knowledge_chunks,
            session_summary=session_summary,
            intent=intent,
        )

        # Step 5: Build message history for LLM
        llm_messages = self._build_llm_messages(session_messages, user_message)

        # Step 6: Generate response
        llm_response = await self.llm.generate_response(
            system_prompt=system_prompt,
            messages=llm_messages,
        )

        response_text = llm_response["content"]

        # Step 7: Apply guardrail post-processing
        if guardrail_config:
            response_text = self.guardrail.apply_post_processing(
                response_text, guardrail_config
            )

        # Step 8: If intent has an action, append action info
        if intent and intent["confidence"] > 0.7:
            action_text = self._format_intent_action(intent)
            if action_text:
                response_text = f"{response_text}\n\n{action_text}"

        # Step 9: Store messages in session memory
        await self.memory.add_message(session_id, "user", user_message)
        await self.memory.add_message(session_id, "assistant", response_text)

        sources = [c.get("title", "") for c in knowledge_chunks if c.get("title")]

        return {
            "response": response_text,
            "intent": intent,
            "tokens_used": llm_response["tokens_used"],
            "sources": sources,
        }

    def _build_system_prompt(
        self,
        guardrail_config: Optional[dict],
        knowledge_chunks: list[dict],
        session_summary: Optional[str],
        intent: Optional[dict],
    ) -> str:
        parts = []

        # Base persona from guardrails
        if guardrail_config:
            persona = guardrail_config.get("persona", {})
            name = persona.get("name", "AI Concierge")
            tone = persona.get("tone", "professional and helpful")
            greeting = persona.get("greeting", "")
            parts.append(
                f"You are {name}, an AI hotel concierge. "
                f"Your tone is: {tone}."
            )
            if greeting:
                parts.append(f"When greeting guests for the first time, use: {greeting}")

            # Allowed/blocked topics
            allowed = guardrail_config.get("allowed_topics", [])
            blocked = guardrail_config.get("blocked_topics", [])
            if allowed:
                parts.append(f"You may help with these topics: {', '.join(allowed)}.")
            if blocked:
                parts.append(
                    f"You must NOT discuss these topics: {', '.join(blocked)}. "
                    "Politely redirect the guest if they ask about these."
                )

            # Custom rules
            custom_rules = guardrail_config.get("custom_rules", [])
            if custom_rules:
                rules_text = "\n".join(f"- {rule}" for rule in custom_rules)
                parts.append(f"Follow these rules strictly:\n{rules_text}")

            # Response limits
            limits = guardrail_config.get("response_limits", {})
            max_len = limits.get("max_response_length")
            if max_len:
                parts.append(f"Keep responses under {max_len} characters.")
        else:
            parts.append(
                "You are a helpful AI hotel concierge. "
                "Be professional, concise, and helpful."
            )

        # Inject knowledge context
        if knowledge_chunks:
            context_text = "\n\n".join(
                f"[{c.get('title', 'Info')}]: {c['content']}"
                for c in knowledge_chunks
            )
            parts.append(
                f"Use the following knowledge base information to answer the guest's question. "
                f"Only use information from this context. If the answer is not in the context, "
                f"say you'll check with the front desk.\n\n{context_text}"
            )

        # Session summary
        if session_summary:
            parts.append(
                f"Previous conversation summary: {session_summary}"
            )

        # Intent hint
        if intent and intent["confidence"] > 0.5:
            parts.append(
                f"The guest's message likely relates to: {intent['intent_name']} "
                f"(confidence: {intent['confidence']:.0%}). "
                f"Consider this when formulating your response."
            )

        parts.append(
            "Always respond in the same language the guest uses. "
            "If you cannot help, offer to connect them with a human staff member."
        )

        return "\n\n".join(parts)

    def _build_llm_messages(
        self,
        session_messages: list[dict],
        current_message: str,
    ) -> list[dict]:
        messages = []
        for msg in session_messages:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
        messages.append({"role": "user", "content": current_message})
        return messages

    def _format_intent_action(self, intent: dict) -> Optional[str]:
        action_type = intent.get("action_type")
        config = intent.get("action_config", {})

        if action_type == "link":
            url = config.get("url", "")
            label = config.get("label", "Click here")
            if url:
                return f"{label}: {url}"

        if action_type == "api_call":
            fallback = config.get("fallback_link", "")
            if fallback:
                return f"You can complete this here: {fallback}"

        return None


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    if not text:
        return []

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap

    return chunks
