import json
import logging
from typing import Optional
from datetime import datetime

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MemoryService:
    """
    Session memory management using Redis.
    Maintains per-guest conversation context with rolling window + summarization.
    """

    def __init__(self):
        self.redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        self.max_turns = settings.session_max_turns
        self.session_timeout = settings.session_timeout_minutes * 60
        self.summary_threshold = settings.session_summary_threshold

    def _session_key(self, session_id: str) -> str:
        return f"session:{session_id}:messages"

    def _summary_key(self, session_id: str) -> str:
        return f"session:{session_id}:summary"

    def _meta_key(self, session_id: str) -> str:
        return f"session:{session_id}:meta"

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ):
        """Add a message to the session history."""
        key = self._session_key(session_id)
        message = json.dumps({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })

        pipe = self.redis.pipeline()
        pipe.rpush(key, message)
        pipe.expire(key, self.session_timeout)
        await pipe.execute()

        # Check if we need to trim
        length = await self.redis.llen(key)
        if length > self.max_turns * 2:
            # Keep only the last max_turns messages
            await self.redis.ltrim(key, -self.max_turns * 2, -1)

    async def get_session_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Get recent messages from session."""
        key = self._session_key(session_id)
        if limit is None:
            limit = self.max_turns * 2  # user + assistant pairs

        raw_messages = await self.redis.lrange(key, -limit, -1)
        messages = []
        for raw in raw_messages:
            try:
                msg = json.loads(raw)
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return messages

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """Get the rolling summary of older conversation."""
        return await self.redis.get(self._summary_key(session_id))

    async def set_session_summary(self, session_id: str, summary: str):
        """Store a conversation summary."""
        key = self._summary_key(session_id)
        await self.redis.set(key, summary, ex=self.session_timeout)

    async def get_session_meta(self, session_id: str) -> Optional[dict]:
        """Get session metadata."""
        raw = await self.redis.get(self._meta_key(session_id))
        if raw:
            return json.loads(raw)
        return None

    async def set_session_meta(self, session_id: str, meta: dict):
        """Store session metadata (tenant_id, guest_phone, etc.)."""
        key = self._meta_key(session_id)
        await self.redis.set(key, json.dumps(meta), ex=self.session_timeout)

    async def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in session."""
        return await self.redis.llen(self._session_key(session_id))

    async def clear_session(self, session_id: str):
        """Clear all session data."""
        pipe = self.redis.pipeline()
        pipe.delete(self._session_key(session_id))
        pipe.delete(self._summary_key(session_id))
        pipe.delete(self._meta_key(session_id))
        await pipe.execute()

    async def close(self):
        await self.redis.aclose()
