"""
Unit tests for GeminiLLMService and Provider Factory.

Tests cover:
1. Gemini response with valid structured JSON
2. Gemini response with multiple extracted fields
3. Gemini response with ambiguity
4. Gemini response with correction
5. Gemini malformed JSON handling
6. Gemini invalid enum handling
7. Gemini invalid field types handling
8. Gemini API/network failure handling
9. Missing Gemini API key handling
10. Provider factory selecting mock
11. Provider factory selecting Gemini
12. Provider factory configuration errors
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from backend.llm.base import LLMServiceError, LLMMalformedResponseError
from backend.llm.factory import get_llm_service, LLMConfigurationError
from backend.llm.gemini_llm import GeminiLLMService
from backend.llm.mock_llm import MockLLMService
from backend.schemas import IntakeState, IntentType, LLMResponse


class TestGeminiLLMService:
    @pytest.fixture
    def gemini_service(self):
        return GeminiLLMService(api_key="fake-test-key", model_name="gemini-2.5-flash")

    def test_1_valid_structured_json(self, gemini_service):
        """Test 1: Parses valid JSON response from Gemini."""
        fake_api_response = json.dumps({
            "intent": "inform",
            "extracted_fields": {
                "full_name": "Karan Deshmukh",
                "home_address": "Nagpur, India",
            },
            "ambiguity_reason": None,
            "contradiction_reason": None,
            "assistant_reply": "Thank you, Karan. I have recorded your details.",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_api_response):
            resp = gemini_service.generate_response("My name is Karan", IntakeState())

            assert isinstance(resp, LLMResponse)
            assert resp.intent == IntentType.INFORM
            assert resp.extracted_fields.full_name == "Karan Deshmukh"
            assert resp.extracted_fields.home_address == "Nagpur, India"
            assert "Thank you" in resp.assistant_reply

    def test_2_multiple_extracted_fields(self, gemini_service):
        """Test 2: Parses multi-field payload with children and executor."""
        fake_payload = json.dumps({
            "intent": "inform",
            "extracted_fields": {
                "full_name": "Karan Deshmukh",
                "home_address": "Nagpur",
                "has_children": True,
                "children": ["Ananya", "Rohan"],
                "executor": {"name": "Rahul", "relationship": "Brother"},
                "specific_gifts": [{"recipient": "Ananya", "item_or_amount": "Watch"}],
            },
            "ambiguity_reason": None,
            "contradiction_reason": None,
            "assistant_reply": "Got all your details.",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_payload):
            resp = gemini_service.generate_response("Everything", IntakeState())

            assert resp.extracted_fields.has_children is True
            assert resp.extracted_fields.children == ["Ananya", "Rohan"]
            assert resp.extracted_fields.executor.name == "Rahul"
            assert resp.extracted_fields.executor.relationship == "Brother"
            assert len(resp.extracted_fields.specific_gifts) == 1

    def test_3_ambiguity_response(self, gemini_service):
        """Test 3: Parses ambiguous response correctly."""
        fake_payload = json.dumps({
            "intent": "ambiguous",
            "extracted_fields": {},
            "ambiguity_reason": "Unclear scope.",
            "contradiction_reason": None,
            "assistant_reply": "Could you please clarify what you mean by everything?",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_payload):
            resp = gemini_service.generate_response("Everything", IntakeState())
            assert resp.intent == IntentType.AMBIGUOUS
            assert resp.ambiguity_reason == "Unclear scope."
            assert "clarify" in resp.assistant_reply

    def test_4_correction_response(self, gemini_service):
        """Test 4: Parses correction intent correctly."""
        fake_payload = json.dumps({
            "intent": "correction",
            "extracted_fields": {
                "executor": {"name": "Amit", "relationship": None}
            },
            "ambiguity_reason": None,
            "contradiction_reason": None,
            "assistant_reply": "Updated executor to Amit.",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_payload):
            resp = gemini_service.generate_response("Actually Amit", IntakeState())
            assert resp.intent == IntentType.CORRECTION
            assert resp.extracted_fields.executor.name == "Amit"

    def test_5_malformed_json_raises_error(self, gemini_service):
        """Test 5: Non-JSON raw text raises LLMMalformedResponseError."""
        with patch.object(gemini_service, "_call_gemini_api", return_value="This is not valid json at all"):
            with pytest.raises(LLMMalformedResponseError) as exc_info:
                gemini_service.generate_response("Hello", IntakeState())
            assert "not valid JSON" in str(exc_info.value)

    def test_6_invalid_enum_raises_error(self, gemini_service):
        """Test 6: Invalid intent enum raises LLMMalformedResponseError."""
        fake_payload = json.dumps({
            "intent": "invalid_intent_value",
            "extracted_fields": {},
            "assistant_reply": "Hello",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_payload):
            with pytest.raises(LLMMalformedResponseError):
                gemini_service.generate_response("Hello", IntakeState())

    def test_7_invalid_field_types_raises_error(self, gemini_service):
        """Test 7: Incompatible field type raises LLMMalformedResponseError."""
        fake_payload = json.dumps({
            "intent": "inform",
            "extracted_fields": {
                "covers_worldwide_assets": "not_a_boolean",
            },
            "assistant_reply": "Hello",
        })

        with patch.object(gemini_service, "_call_gemini_api", return_value=fake_payload):
            with pytest.raises(LLMMalformedResponseError):
                gemini_service.generate_response("Hello", IntakeState())

    def test_8_api_network_failure(self, gemini_service):
        """Test 8: Network or HTTP failure raises LLMServiceError."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
            with pytest.raises(LLMServiceError) as exc_info:
                gemini_service.generate_response("Hello", IntakeState())
            assert "timed out" in str(exc_info.value).lower()

    def test_9_missing_api_key_raises(self):
        """Test 9: Instantiating GeminiLLMService without API key raises LLMServiceError."""
        with patch("backend.config.settings.GEMINI_API_KEY", None):
            with pytest.raises(LLMServiceError) as exc_info:
                GeminiLLMService(api_key=None)
            assert "API key is not configured" in str(exc_info.value)


class TestProviderFactory:
    def test_10_factory_selects_mock(self):
        """Test 10: Factory returns MockLLMService when provider is 'mock'."""
        service = get_llm_service(provider="mock")
        assert isinstance(service, MockLLMService)

    def test_11_factory_selects_gemini(self):
        """Test 11: Factory returns GeminiLLMService when provider is 'gemini' with key."""
        with patch("backend.config.settings.GEMINI_API_KEY", "valid-fake-key"):
            service = get_llm_service(provider="gemini")
            assert isinstance(service, GeminiLLMService)

    def test_12_factory_missing_gemini_key_raises(self):
        """Test 12: Selecting 'gemini' without API key raises LLMConfigurationError."""
        with patch("backend.config.settings.GEMINI_API_KEY", None):
            with pytest.raises(LLMConfigurationError) as exc_info:
                get_llm_service(provider="gemini")
            assert "GEMINI_API_KEY is not set" in str(exc_info.value)

    def test_13_factory_unknown_provider_raises(self):
        """Test 13: Unsupported provider name raises LLMConfigurationError."""
        with pytest.raises(LLMConfigurationError) as exc_info:
            get_llm_service(provider="openai_unsupported")
        assert "Unsupported LLM_PROVIDER" in str(exc_info.value)
