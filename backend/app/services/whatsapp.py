import hmac
import hashlib
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WhatsAppService:
    """Client for the Meta WhatsApp Cloud API."""

    def __init__(self):
        self.api_url = settings.whatsapp_api_url
        self.client = httpx.AsyncClient(timeout=30)

    async def send_text_message(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        text: str,
    ) -> dict:
        """Send a text message via WhatsApp."""
        url = f"{self.api_url}/{phone_number_id}/messages"
        response = await self.client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": True, "body": text},
            },
        )
        response.raise_for_status()
        return response.json()

    async def send_interactive_buttons(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        body_text: str,
        buttons: list[dict],
    ) -> dict:
        """Send an interactive button message (max 3 buttons)."""
        button_items = []
        for i, btn in enumerate(buttons[:3]):
            button_items.append({
                "type": "reply",
                "reply": {
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn["title"][:20],  # max 20 chars
                },
            })

        url = f"{self.api_url}/{phone_number_id}/messages"
        response = await self.client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text},
                    "action": {"buttons": button_items},
                },
            },
        )
        response.raise_for_status()
        return response.json()

    async def send_interactive_list(
        self,
        phone_number_id: str,
        access_token: str,
        to: str,
        body_text: str,
        button_text: str,
        sections: list[dict],
    ) -> dict:
        """Send an interactive list message."""
        url = f"{self.api_url}/{phone_number_id}/messages"
        response = await self.client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body_text},
                    "action": {
                        "button": button_text[:20],
                        "sections": sections,
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()

    async def mark_as_read(
        self,
        phone_number_id: str,
        access_token: str,
        message_id: str,
    ):
        """Mark a message as read."""
        url = f"{self.api_url}/{phone_number_id}/messages"
        await self.client.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
        )

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        """Verify the X-Hub-Signature-256 header from Meta."""
        if not settings.whatsapp_app_secret:
            logger.warning("WhatsApp app secret not configured, skipping signature verification")
            return True

        secret = settings.whatsapp_app_secret
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        expected_sig = f"sha256={expected}"
        match = hmac.compare_digest(expected_sig, signature)

        if not match:
            logger.error(
                f"Webhook signature mismatch: "
                f"received_sig_prefix={signature[:20]}..., "
                f"expected_sig_prefix={expected_sig[:20]}..., "
                f"secret_len={len(secret)}, "
                f"payload_len={len(payload)}"
            )

        return match

    @staticmethod
    def extract_message(payload: dict) -> Optional[dict]:
        """Extract message details from a WhatsApp webhook payload."""
        try:
            entry = payload.get("entry", [])
            if not entry:
                return None

            changes = entry[0].get("changes", [])
            if not changes:
                return None

            value = changes[0].get("value", {})
            messages = value.get("messages", [])
            if not messages:
                return None

            msg = messages[0]
            contacts = value.get("contacts", [])
            sender_name = contacts[0]["profile"]["name"] if contacts else "Guest"

            phone_number_id = value.get("metadata", {}).get("phone_number_id", "")

            result = {
                "message_id": msg.get("id", ""),
                "from": msg.get("from", ""),
                "sender_name": sender_name,
                "timestamp": msg.get("timestamp", ""),
                "phone_number_id": phone_number_id,
                "type": msg.get("type", "text"),
            }

            if msg.get("type") == "text":
                result["text"] = msg["text"]["body"]
            elif msg.get("type") == "interactive":
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    result["text"] = interactive["button_reply"]["title"]
                    result["button_id"] = interactive["button_reply"]["id"]
                elif interactive.get("type") == "list_reply":
                    result["text"] = interactive["list_reply"]["title"]
                    result["list_id"] = interactive["list_reply"]["id"]
            else:
                result["text"] = f"[Unsupported message type: {msg.get('type')}]"

            return result

        except (KeyError, IndexError) as e:
            logger.error(f"Failed to extract message from webhook: {e}")
            return None

    async def close(self):
        await self.client.aclose()
