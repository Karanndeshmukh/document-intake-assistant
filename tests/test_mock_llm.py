"""
Unit tests for MockLLMService.

Tests cover:
1. Simple full-name extraction
2. Multiple-field extraction
3. Partial executor extraction (name only, relationship remains None)
4. Executor relationship follow-up
5. Explicit correction intent and payload
6. Ambiguous input detection
7. Contradiction scenario simulation
8. Off-topic query handling
9. Valid LLMResponse schema validation
10. Malformed response boundary error handling
"""

import pytest

from backend.llm.base import LLMMalformedResponseError
from backend.llm.mock_llm import MockLLMService, MockMode
from backend.schemas import (
    ChatMessage,
    Executor,
    IntakeState,
    IntentType,
    LLMResponse,
    MessageRole,
)


class TestMockLLMService:
    @pytest.fixture
    def mock_service(self):
        return MockLLMService()

    def test_1_simple_full_name_extraction(self, mock_service):
        """Test 1: Extract full name from natural language greeting."""
        state = IntakeState()
        response = mock_service.generate_response("My name is Karan Deshmukh", state)

        assert isinstance(response, LLMResponse)
        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan Deshmukh"
        assert "Karan" in response.assistant_reply
        assert "address" in response.assistant_reply.lower()

    def test_2_multiple_field_extraction(self, mock_service):
        """Test 2: Extract multi-field input in a single turn."""
        state = IntakeState()
        user_msg = (
            "My name is Karan Deshmukh, I live in Nagpur, I don't have children, "
            "and my brother Rahul is my executor."
        )
        response = mock_service.generate_response(user_msg, state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan Deshmukh"
        assert response.extracted_fields.home_address == "Nagpur"
        assert response.extracted_fields.has_children is False
        assert response.extracted_fields.children == []
        assert response.extracted_fields.executor is not None
        assert response.extracted_fields.executor.name == "Rahul"
        assert response.extracted_fields.executor.relationship == "Brother"

    def test_3_partial_executor_extraction(self, mock_service):
        """Test 3: Extract only executor name without inventing relationship."""
        state = IntakeState(full_name="Karan Deshmukh", home_address="Nagpur")
        response = mock_service.generate_response("Rahul is my executor.", state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.executor is not None
        assert response.extracted_fields.executor.name == "Rahul"
        assert response.extracted_fields.executor.relationship is None
        assert "relationship" in response.assistant_reply.lower()

    def test_4_executor_relationship_followup(self, mock_service):
        """Test 4: Extract relationship follow-up utterance."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            executor=Executor(name="Rahul", relationship=None),
        )
        response = mock_service.generate_response("He is my brother", state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.executor is not None
        assert response.extracted_fields.executor.relationship == "Brother"
        assert response.extracted_fields.executor.name is None

    def test_5_explicit_correction(self, mock_service):
        """Test 5: Categorize correction intent and extract target replacement field."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        response = mock_service.generate_response("Actually, change my executor to Amit", state)

        assert response.intent == IntentType.CORRECTION
        assert response.extracted_fields.executor is not None
        assert response.extracted_fields.executor.name == "Amit"
        assert "update" in response.assistant_reply.lower()

    def test_6_ambiguous_input(self, mock_service):
        """Test 6: Flag ambiguous statements without fabricating worldwide coverage."""
        state = IntakeState(full_name="Karan Deshmukh")
        response = mock_service.generate_response("I want everything covered.", state)

        assert response.intent == IntentType.AMBIGUOUS
        assert response.ambiguity_reason is not None
        assert "everything covered" in response.ambiguity_reason
        assert response.extracted_fields.covers_worldwide_assets is None
        assert "worldwide" in response.assistant_reply.lower()

    def test_7_contradiction_simulation(self, mock_service):
        """Test 7: Extract conflicting candidate data while leaving state protection to ValidationEngine."""
        state = IntakeState(has_children=False, children=[])
        response = mock_service.generate_response("My daughter Ananya should receive my car", state)

        # Mock extracts the daughter and gift candidates
        assert response.extracted_fields.has_children is True
        assert response.extracted_fields.children == ["Ananya"]
        assert len(response.extracted_fields.specific_gifts) == 1
        assert response.extracted_fields.specific_gifts[0].recipient == "Ananya"

    def test_8_off_topic_input(self, mock_service):
        """Test 8: Identify off-topic questions and politely steer user back to document intake."""
        state = IntakeState()
        response = mock_service.generate_response("What is the weather forecast today?", state)

        assert response.intent == IntentType.OFF_TOPIC
        assert "Personal Wishes Document" in response.assistant_reply

    def test_9_valid_llm_response_validation(self, mock_service):
        """Test 9: Output adheres strictly to the LLMResponse schema."""
        state = IntakeState()
        response = mock_service.generate_response("I live in Nagpur, India", state)

        assert isinstance(response, LLMResponse)
        assert response.extracted_fields.home_address == "Nagpur, India"
        assert response.assistant_reply != ""

    def test_10_malformed_response_handling(self, mock_service):
        """Test 10: Fault injection modes raise LLMMalformedResponseError as expected."""
        state = IntakeState()

        # Mode A: Malformed JSON syntax
        mock_service.set_mode(MockMode.MALFORMED_JSON)
        with pytest.raises(LLMMalformedResponseError):
            mock_service.generate_response("Hello", state)

        # Mode B: Invalid schema (missing required fields)
        mock_service.set_mode(MockMode.INVALID_SCHEMA)
        with pytest.raises(LLMMalformedResponseError):
            mock_service.generate_response("Hello", state)

        # Mode C: Invalid Enum value
        mock_service.set_mode(MockMode.INVALID_ENUM)
        with pytest.raises(LLMMalformedResponseError):
            mock_service.generate_response("Hello", state)

        # Mode D: Invalid nested types
        mock_service.set_mode(MockMode.INVALID_TYPES)
        with pytest.raises(LLMMalformedResponseError):
            mock_service.generate_response("Hello", state)

    @pytest.mark.parametrize(
        "user_input",
        [
            "only in my home country",
            "home country only",
            "not worldwide",
            "just my home country",
            "no, only my country",
            "only in my country",
            "no, not worldwide",
        ],
    )
    def test_11_worldwide_assets_negative_phrases(self, mock_service, user_input):
        """Test 11: Negative natural phrasing maps correctly to covers_worldwide_assets=False."""
        state = IntakeState(full_name="Karan Deshmukh", home_address="Nagpur")
        response = mock_service.generate_response(user_input, state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.covers_worldwide_assets is False
        assert "worldwide" not in response.assistant_reply.lower() or "children" in response.assistant_reply.lower()

    @pytest.mark.parametrize(
        "user_input",
        [
            "yes, worldwide",
            "globally",
            "worldwide",
            "all my assets worldwide",
            "yes",
        ],
    )
    def test_12_worldwide_assets_positive_phrases(self, mock_service, user_input):
        """Test 12: Positive natural phrasing maps correctly to covers_worldwide_assets=True."""
        state = IntakeState(full_name="Karan Deshmukh", home_address="Nagpur")
        response = mock_service.generate_response(user_input, state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.covers_worldwide_assets is True
        assert "children" in response.assistant_reply.lower()

    def test_13_direct_name_extraction_full_name(self, mock_service):
        """Test 13: Context question 'May I please have your full legal name?' + user 'Karan Deshmukh' -> full_name='Karan Deshmukh'."""
        state = IntakeState()
        history = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="To get started, may I please have your full legal name?",
            )
        ]
        response = mock_service.generate_response("Karan Deshmukh", state, history=history)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan Deshmukh"
        assert "Karan Deshmukh" in response.assistant_reply or "address" in response.assistant_reply.lower()

    def test_14_direct_name_extraction_single_name(self, mock_service):
        """Test 14: Context question + single name 'Karan' -> full_name='Karan'."""
        state = IntakeState()
        history = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="May I please have your full legal name?",
            )
        ]
        response = mock_service.generate_response("Karan", state, history=history)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan"

    def test_15_existing_explicit_name_form(self, mock_service):
        """Test 15: Existing explicit form 'My name is Karan Deshmukh' -> full_name='Karan Deshmukh'."""
        state = IntakeState()
        response = mock_service.generate_response("My name is Karan Deshmukh", state)

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan Deshmukh"

    def test_16_existing_multi_field_form(self, mock_service):
        """Test 16: Multi-field form 'My name is Karan Deshmukh and I live in Nagpur.' -> full_name + home_address."""
        state = IntakeState()
        response = mock_service.generate_response(
            "My name is Karan Deshmukh and I live in Nagpur.", state
        )

        assert response.intent == IntentType.INFORM
        assert response.extracted_fields.full_name == "Karan Deshmukh"
        assert response.extracted_fields.home_address == "Nagpur"

    def test_17_short_unrelated_response_not_stored_as_name_when_not_asking(self, mock_service):
        """Test 17: Short responses are NOT stored as full_name when context is asking a different question."""
        state = IntakeState(full_name="Karan Deshmukh", home_address="Nagpur")
        history = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="Who would you like to appoint as the executor of your wishes?",
            )
        ]
        # User answers with executor relationship follow-up or address, not name
        response = mock_service.generate_response("He is my brother", state, history=history)
        assert response.extracted_fields.full_name is None

        # When asking for children
        state_child = IntakeState(full_name="Karan Deshmukh", home_address="Nagpur", covers_worldwide_assets=True)
        history_child = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="Do you have any children?",
            )
        ]
        response_child = mock_service.generate_response("No children", state_child, history=history_child)
        assert response_child.extracted_fields.full_name is None

    # ------------------------------------------------------------------
    # Tests 18-22: Context-aware home address extraction
    # ------------------------------------------------------------------

    def _address_state(self) -> IntakeState:
        """Convenience: state with name filled, address missing."""
        return IntakeState(full_name="Karan Deshmukh")

    def _address_history(self) -> list:
        """Convenience: last assistant message is asking for residential address."""
        return [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content="Nice to meet you, Karan Deshmukh. What is your current residential home address?",
            )
        ]

    def test_18_concise_city_name_as_address(self, mock_service):
        """Test 18: 'Nagpur' with address-question context -> home_address == 'Nagpur'."""
        response = mock_service.generate_response(
            "Nagpur", self._address_state(), history=self._address_history()
        )
        assert response.extracted_fields.home_address == "Nagpur"
        assert "worldwide" in response.assistant_reply.lower()

    def test_19_city_and_country_as_address(self, mock_service):
        """Test 19: 'Nagpur India' with address-question context -> home_address == 'Nagpur India'."""
        response = mock_service.generate_response(
            "Nagpur India", self._address_state(), history=self._address_history()
        )
        assert response.extracted_fields.home_address == "Nagpur India"
        assert "worldwide" in response.assistant_reply.lower()

    def test_20_full_street_address(self, mock_service):
        """Test 20: '123 MG Road, Nagpur' with address-question context -> home_address captured."""
        response = mock_service.generate_response(
            "123 MG Road, Nagpur", self._address_state(), history=self._address_history()
        )
        assert response.extracted_fields.home_address == "123 MG Road, Nagpur"

    def test_21_explicit_address_form_preserved(self, mock_service):
        """Test 21: Existing explicit form 'I live in Nagpur' -> home_address='Nagpur' without context needed."""
        state = IntakeState(full_name="Karan Deshmukh")
        response = mock_service.generate_response("I live in Nagpur", state)
        assert response.extracted_fields.home_address == "Nagpur"

    # ------------------------------------------------------------------
    # Tests 23-24: Optional gifts & additional wishes negative/off-topic handling
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "negative_reply",
        [
            "no",
            "none",
            "nothing",
            "nothing else",
            "no specific gifts",
            "no additional wishes",
            "I don't have any",
            "I have none",
            "no gifts",
            "no thanks",
        ],
    )
    def test_23_negative_optional_responses(self, mock_service, negative_reply):
        """Test 23: Clear negative responses to optional questions leave gifts/wishes empty and conclude intake."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            covers_worldwide_assets=True,
            has_children=False,
            children=[],
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        history = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=(
                    "We have captured all essential details for your draft document. "
                    "Do you have any specific gifts you would like to assign, or any additional wishes to include?"
                ),
            )
        ]
        response = mock_service.generate_response(negative_reply, state, history=history)

        assert response.intent == IntentType.INFORM
        assert not response.extracted_fields.specific_gifts
        assert response.extracted_fields.additional_wishes is None
        assert "complete" in response.assistant_reply.lower()
        assert "specific gifts" not in response.assistant_reply.lower()

    def test_24_unrelated_input_not_stored_as_gift_or_wish(self, mock_service):
        """Test 24: Unrelated greetings/off-topic such as 'happy birthday' are not extracted as gifts or wishes."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            covers_worldwide_assets=True,
            has_children=False,
            children=[],
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        history = [
            ChatMessage(
                role=MessageRole.ASSISTANT,
                content=(
                    "We have captured all essential details for your draft document. "
                    "Do you have any specific gifts you would like to assign, or any additional wishes to include?"
                ),
            )
        ]
        response = mock_service.generate_response("happy birthday", state, history=history)

        assert response.intent == IntentType.OFF_TOPIC
        assert not response.extracted_fields.specific_gifts
        assert response.extracted_fields.additional_wishes is None



