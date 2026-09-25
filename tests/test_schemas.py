"""
Unit tests for Pydantic schemas in Document Intake Assistant.

Tests cover:
1. Structured state schema defaults (explicit unknowns remain None)
2. Executor validation (partial, complete, whitespace stripping)
3. Children validation (consistency rules, deduplication)
4. Specific gifts validation (valid item/recipient, non-empty)
5. Typed LLM extraction schema and intent types
6. Session model and pending clarifications
7. API request/response serialization
"""

import pytest
from pydantic import ValidationError

from backend.schemas import (
    IntakeState,
    Executor,
    SpecificGift,
    IntentType,
    ExtractedFields,
    LLMResponse,
    ChatMessage,
    MessageRole,
    PendingClarification,
    SessionState,
    ChatRequest,
    ChatResponse,
    SessionInitResponse,
)


class TestIntakeStateSchemas:
    def test_default_state_is_explicitly_unknown(self):
        """Verify that newly initialized state has explicitly null values and never invents data."""
        state = IntakeState()
        assert state.full_name is None
        assert state.home_address is None
        assert state.covers_worldwide_assets is None
        assert state.has_children is None
        assert state.children == []
        assert state.executor.name is None
        assert state.executor.relationship is None
        assert state.specific_gifts == []
        assert state.additional_wishes is None
        assert not state.is_complete
        assert set(state.get_missing_fields()) == {
            "full_name",
            "home_address",
            "covers_worldwide_assets",
            "has_children",
            "executor_name",
            "executor_relationship",
        }

    def test_whitespace_is_cleaned_to_none_or_trimmed(self):
        """String fields with only whitespace should normalize to None."""
        state = IntakeState(full_name="   ", home_address="  Nagpur  ")
        assert state.full_name is None
        assert state.home_address == "Nagpur"

    def test_executor_validation(self):
        """Executor must support partial info without inventing relationship."""
        # Only name known
        exec_only_name = Executor(name="Rahul", relationship=None)
        assert exec_only_name.name == "Rahul"
        assert exec_only_name.relationship is None
        assert not exec_only_name.is_complete
        assert not exec_only_name.is_empty

        # Complete executor
        exec_complete = Executor(name="Rahul Deshmukh", relationship="Brother")
        assert exec_complete.is_complete

        # Whitespace handling
        exec_ws = Executor(name="  Amit  ", relationship="  ")
        assert exec_ws.name == "Amit"
        assert exec_ws.relationship is None

    def test_children_consistency_validation(self):
        """Children list must be consistent with has_children flag."""
        # When has_children is False, children list cannot have items
        with pytest.raises(ValidationError):
            IntakeState(has_children=False, children=["Ananya"])

        # When has_children is False with empty list, it succeeds
        state_no_kids = IntakeState(has_children=False, children=[])
        assert state_no_kids.has_children is False
        assert state_no_kids.children == []

        # Deduplication and whitespace trimming on children list
        state_with_kids = IntakeState(children=[" Ananya ", "Rohan", "Ananya"])
        assert state_with_kids.children == ["Ananya", "Rohan"]
        assert state_with_kids.has_children is True

    def test_specific_gift_validation(self):
        """SpecificGift must have non-empty recipient and item description."""
        gift = SpecificGift(recipient="Ananya", item_or_amount="Gold watch")
        assert gift.recipient == "Ananya"
        assert gift.item_or_amount == "Gold watch"

        # Empty recipient should fail
        with pytest.raises(ValidationError):
            SpecificGift(recipient="   ", item_or_amount="Watch")

        # Empty item description should fail
        with pytest.raises(ValidationError):
            SpecificGift(recipient="Ananya", item_or_amount="")

    def test_is_complete_and_missing_fields(self):
        """State is complete only when all mandatory intake questions are answered."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur, Maharashtra",
            covers_worldwide_assets=True,
            has_children=False,
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        assert state.is_complete
        assert state.get_missing_fields() == []


class TestTypedLLMSchemas:
    def test_intent_type_enum_values(self):
        """Ensure all required intent types are supported."""
        assert IntentType.INFORM == "inform"
        assert IntentType.CORRECTION == "correction"
        assert IntentType.AMBIGUOUS == "ambiguous"
        assert IntentType.CONTRADICTION == "contradiction"
        assert IntentType.OFF_TOPIC == "off_topic"

    def test_extracted_fields_strongly_typed(self):
        """ExtractedFields should parse nested Pydantic models correctly."""
        extracted = ExtractedFields(
            full_name="Karan Deshmukh",
            executor=Executor(name="Rahul", relationship="Brother"),
            specific_gifts=[SpecificGift(recipient="Rohan", item_or_amount="Car")],
        )
        assert extracted.full_name == "Karan Deshmukh"
        assert extracted.executor.name == "Rahul"
        assert extracted.executor.relationship == "Brother"
        assert len(extracted.specific_gifts) == 1
        assert extracted.specific_gifts[0].recipient == "Rohan"

    def test_llm_response_structure(self):
        """LLMResponse must enforce intent and assistant_reply."""
        resp = LLMResponse(
            intent=IntentType.INFORM,
            extracted_fields=ExtractedFields(full_name="Karan"),
            assistant_reply="Thank you, Karan. Where do you currently live?",
        )
        assert resp.intent == IntentType.INFORM
        assert resp.extracted_fields.full_name == "Karan"
        assert resp.assistant_reply.startswith("Thank you")

        # Empty assistant_reply should fail
        with pytest.raises(ValidationError):
            LLMResponse(intent=IntentType.INFORM, assistant_reply="")


class TestSessionModel:
    def test_session_state_initialization(self):
        """SessionState initializes with a unique session_id, default IntakeState, and empty history."""
        session = SessionState()
        assert session.session_id is not None
        assert isinstance(session.state, IntakeState)
        assert session.conversation_history == []
        assert session.pending_clarification is None

    def test_chat_message_creation(self):
        """ChatMessage stores role and timestamp."""
        msg = ChatMessage(role=MessageRole.USER, content="Hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"
        assert msg.id is not None
        assert msg.timestamp is not None

    def test_pending_clarification_model(self):
        """PendingClarification records field and reason for contradiction/ambiguity."""
        pending = PendingClarification(
            field_name="has_children",
            reason="User previously stated no children, but now mentions daughter.",
            current_value=False,
            proposed_value=True,
        )
        assert pending.field_name == "has_children"
        assert pending.current_value is False
        assert pending.proposed_value is True


class TestAPISchemas:
    def test_chat_request_validation(self):
        """ChatRequest rejects blank or whitespace-only messages."""
        req = ChatRequest(session_id="123", message="Hello")
        assert req.message == "Hello"

        with pytest.raises(ValidationError):
            ChatRequest(session_id="123", message="   ")

    def test_chat_response_serialization(self):
        """ChatResponse serializes complete state, draft document, and missing fields."""
        res = ChatResponse(
            session_id="test-session",
            assistant_message="Got it!",
            state=IntakeState(full_name="Karan"),
            draft_document="DRAFT PERSONAL WISHES DOCUMENT",
            missing_fields=["home_address", "covers_worldwide_assets"],
            status="in_progress",
        )
        assert res.session_id == "test-session"
        assert res.state.full_name == "Karan"
        assert len(res.missing_fields) == 2
