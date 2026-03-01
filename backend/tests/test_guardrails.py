import pytest
import yaml

from app.services.guardrail import GuardrailService


class TestGuardrailService:
    def test_form_data_to_yaml(self):
        form_data = {
            "tenant_name": "Grand Hotel",
            "language": ["en", "zh"],
            "persona": {
                "name": "Sofia",
                "tone": "warm, professional",
                "greeting": "Welcome to Grand Hotel!",
            },
            "allowed_topics": ["room_booking", "room_service"],
            "blocked_topics": ["competitor_pricing"],
            "escalation_rules": [
                {"trigger": "speak to human", "action": "transfer_to_human", "contact": "+6591234567"}
            ],
            "response_limits": {
                "max_response_length": 500,
                "max_conversation_turns": 50,
                "session_timeout_minutes": 30,
            },
            "data_handling": {
                "collect_personal_data": False,
                "store_conversation_history": True,
                "retention_days": 90,
            },
            "custom_rules": ["Never quote exact prices"],
        }

        yaml_str = GuardrailService.form_data_to_yaml(form_data)
        config = yaml.safe_load(yaml_str)

        assert config["tenant_name"] == "Grand Hotel"
        assert config["persona"]["name"] == "Sofia"
        assert "room_booking" in config["allowed_topics"]
        assert "competitor_pricing" in config["blocked_topics"]
        assert config["custom_rules"] == ["Never quote exact prices"]

    def test_parse_yaml_valid(self):
        yaml_str = "tenant_name: Test\npersona:\n  name: Bot\n  tone: friendly"
        config = GuardrailService.parse_yaml(yaml_str)
        assert config["tenant_name"] == "Test"

    def test_parse_yaml_invalid(self):
        with pytest.raises(ValueError, match="Invalid YAML"):
            GuardrailService.parse_yaml("invalid: yaml: [broken")

    def test_validate_config_valid(self):
        config = {
            "tenant_name": "Test",
            "persona": {"name": "Bot", "tone": "friendly"},
            "allowed_topics": ["faq"],
            "blocked_topics": ["politics"],
        }
        errors = GuardrailService.validate_config(config)
        assert len(errors) == 0

    def test_validate_config_missing_name(self):
        config = {"persona": {"name": "Bot", "tone": "friendly"}}
        errors = GuardrailService.validate_config(config)
        assert any("tenant_name" in e for e in errors)

    def test_validate_config_overlap_topics(self):
        config = {
            "tenant_name": "Test",
            "persona": {"name": "Bot", "tone": "friendly"},
            "allowed_topics": ["faq"],
            "blocked_topics": ["faq"],
        }
        errors = GuardrailService.validate_config(config)
        assert any("both allowed and blocked" in e for e in errors)

    def test_apply_post_processing_max_length(self):
        config = {"response_limits": {"max_response_length": 50}}
        long_response = "This is a very long response that exceeds the maximum length. It has many sentences."
        result = GuardrailService.apply_post_processing(long_response, config)
        assert len(result) <= 53  # 50 + "..."

    def test_apply_post_processing_blocked_topic(self):
        config = {"blocked_topics": ["competitor"]}
        response = "Our competitor offers lower prices."
        result = GuardrailService.apply_post_processing(response, config)
        assert "not able to help" in result

    def test_check_escalation_match(self):
        config = {
            "escalation_rules": [
                {"trigger": "speak to a human", "action": "transfer_to_human", "contact": "+6591234567"}
            ]
        }
        result = GuardrailService.check_escalation("I want to speak to a human please", config)
        assert result is not None
        assert result["action"] == "transfer_to_human"

    def test_check_escalation_no_match(self):
        config = {
            "escalation_rules": [
                {"trigger": "speak to a human", "action": "transfer_to_human"}
            ]
        }
        result = GuardrailService.check_escalation("What time is checkout?", config)
        assert result is None
