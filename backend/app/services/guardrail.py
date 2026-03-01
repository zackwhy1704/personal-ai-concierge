import logging
import re
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# JSON schema for the web form data that gets converted to YAML
GUARDRAIL_SCHEMA = {
    "type": "object",
    "required": ["tenant_name", "persona"],
    "properties": {
        "tenant_name": {"type": "string", "maxLength": 255},
        "language": {
            "type": "array",
            "items": {"type": "string", "maxLength": 10},
            "maxItems": 20,
        },
        "persona": {
            "type": "object",
            "required": ["name", "tone"],
            "properties": {
                "name": {"type": "string", "maxLength": 100},
                "tone": {"type": "string", "maxLength": 200},
                "greeting": {"type": "string", "maxLength": 500},
            },
        },
        "allowed_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
        "blocked_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
        "escalation_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "trigger": {"type": "string"},
                    "action": {"type": "string", "enum": ["transfer_to_human", "log_and_escalate", "auto_respond"]},
                    "contact": {"type": "string"},
                    "severity_threshold": {"type": "integer"},
                },
            },
        },
        "response_limits": {
            "type": "object",
            "properties": {
                "max_response_length": {"type": "integer", "minimum": 100, "maximum": 2000},
                "max_conversation_turns": {"type": "integer", "minimum": 5, "maximum": 100},
                "session_timeout_minutes": {"type": "integer", "minimum": 5, "maximum": 120},
            },
        },
        "data_handling": {
            "type": "object",
            "properties": {
                "collect_personal_data": {"type": "boolean"},
                "store_conversation_history": {"type": "boolean"},
                "retention_days": {"type": "integer", "minimum": 1, "maximum": 365},
            },
        },
        "custom_rules": {
            "type": "array",
            "items": {"type": "string", "maxLength": 500},
            "maxItems": 50,
        },
    },
}


class GuardrailService:
    """Manages guardrail configuration and enforcement."""

    @staticmethod
    def form_data_to_yaml(form_data: dict) -> str:
        """Convert web form JSON data to YAML config."""
        config = {
            "tenant_name": form_data.get("tenant_name", ""),
            "language": form_data.get("language", ["en"]),
            "persona": {
                "name": form_data.get("persona", {}).get("name", "AI Concierge"),
                "tone": form_data.get("persona", {}).get("tone", "professional and helpful"),
                "greeting": form_data.get("persona", {}).get("greeting", ""),
            },
            "allowed_topics": form_data.get("allowed_topics", []),
            "blocked_topics": form_data.get("blocked_topics", []),
            "escalation_rules": form_data.get("escalation_rules", []),
            "response_limits": {
                "max_response_length": form_data.get("response_limits", {}).get("max_response_length", 500),
                "max_conversation_turns": form_data.get("response_limits", {}).get("max_conversation_turns", 50),
                "session_timeout_minutes": form_data.get("response_limits", {}).get("session_timeout_minutes", 30),
            },
            "data_handling": {
                "collect_personal_data": form_data.get("data_handling", {}).get("collect_personal_data", False),
                "store_conversation_history": form_data.get("data_handling", {}).get("store_conversation_history", True),
                "retention_days": form_data.get("data_handling", {}).get("retention_days", 90),
            },
            "custom_rules": form_data.get("custom_rules", []),
        }
        return yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @staticmethod
    def parse_yaml(yaml_string: str) -> dict:
        """Parse YAML guardrail config string into dict."""
        try:
            config = yaml.safe_load(yaml_string)
            if not isinstance(config, dict):
                raise ValueError("Guardrail config must be a YAML mapping")
            return config
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

    @staticmethod
    def validate_config(config: dict) -> list[str]:
        """Validate guardrail config and return list of errors (empty = valid)."""
        errors = []

        if not config.get("tenant_name"):
            errors.append("tenant_name is required")

        persona = config.get("persona", {})
        if not persona.get("name"):
            errors.append("persona.name is required")
        if not persona.get("tone"):
            errors.append("persona.tone is required")

        blocked = config.get("blocked_topics", [])
        allowed = config.get("allowed_topics", [])
        overlap = set(blocked) & set(allowed)
        if overlap:
            errors.append(f"Topics cannot be both allowed and blocked: {overlap}")

        limits = config.get("response_limits", {})
        max_len = limits.get("max_response_length")
        if max_len is not None and (max_len < 100 or max_len > 2000):
            errors.append("max_response_length must be between 100 and 2000")

        return errors

    @staticmethod
    def apply_post_processing(response: str, config: dict) -> str:
        """Apply guardrail rules to the generated response."""
        # Enforce max length
        limits = config.get("response_limits", {})
        max_len = limits.get("max_response_length")
        if max_len and len(response) > max_len:
            # Truncate at last sentence boundary before max_len
            truncated = response[:max_len]
            last_period = truncated.rfind(".")
            if last_period > max_len * 0.5:
                response = truncated[: last_period + 1]
            else:
                response = truncated.rstrip() + "..."

        # Check for blocked topic mentions (basic keyword check)
        blocked = config.get("blocked_topics", [])
        for topic in blocked:
            pattern = re.compile(re.escape(topic), re.IGNORECASE)
            if pattern.search(response):
                response = (
                    "I'm sorry, I'm not able to help with that topic. "
                    "Is there anything else I can assist you with?"
                )
                break

        return response

    @staticmethod
    def check_escalation(message: str, config: dict) -> Optional[dict]:
        """Check if message triggers an escalation rule."""
        rules = config.get("escalation_rules", [])
        for rule in rules:
            trigger = rule.get("trigger", "")
            if trigger and trigger.lower() in message.lower():
                return {
                    "action": rule.get("action", "transfer_to_human"),
                    "contact": rule.get("contact", ""),
                }
        return None
