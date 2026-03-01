import logging
from typing import Optional

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens

    async def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: Optional[int] = None,
    ) -> dict:
        """
        Generate a response using Claude Haiku.
        Returns {"content": str, "tokens_used": int, "stop_reason": str}
        """
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            system=system_prompt,
            messages=messages,
        )

        content = response.content[0].text if response.content else ""
        tokens_used = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)

        return {
            "content": content,
            "tokens_used": tokens_used,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "stop_reason": response.stop_reason,
        }

    async def summarize_conversation(self, messages: list[dict]) -> str:
        """Summarize older conversation messages into a concise summary."""
        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in messages
        )

        response = await self.generate_response(
            system_prompt=(
                "You are a conversation summarizer. Summarize the following conversation "
                "between a hotel guest and an AI concierge into 2-3 concise sentences. "
                "Focus on key requests, decisions, and any pending actions."
            ),
            messages=[
                {"role": "user", "content": f"Summarize this conversation:\n\n{conversation_text}"}
            ],
            max_tokens=200,
        )

        return response["content"]

    async def extract_parameters(
        self,
        message: str,
        required_params: list[str],
        context: str = "",
    ) -> dict:
        """Extract structured parameters from a user message for API calls."""
        params_list = ", ".join(required_params)
        response = await self.generate_response(
            system_prompt=(
                "You are a parameter extraction assistant. Extract the requested parameters "
                "from the user's message. Return ONLY a JSON object with the parameter names "
                "as keys. Use null for any parameter not found in the message. "
                "Do not include any text outside the JSON."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract these parameters: {params_list}\n\n"
                        f"Context: {context}\n\n"
                        f"User message: {message}"
                    ),
                }
            ],
            max_tokens=300,
        )

        import json
        try:
            return json.loads(response["content"])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM parameter extraction: {response['content']}")
            return {}
