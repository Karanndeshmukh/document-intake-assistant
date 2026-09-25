"""
Unit and integration tests for ConversationOrchestrator.

Tests cover all 15 integration requirements:
1. Simple single-turn extraction
2. Multi-turn executor conversation
3. Multi-field extraction
4. Ambiguous input
5. Contradictory input
6. Explicit correction
7. Unknown information remains unknown
8. Off-topic input
9. Malformed LLM response handling
10. LLM service failure handling
11. Missing session handling
12. State is unchanged after validation failure
13. State is unchanged after LLM failure
14. User and assistant messages are recorded correctly in history
15. Multiple sessions remain completely isolated
"""

import pytest

from backend.conversation import ConversationOrchestrator, OrchestratorResult
from backend.llm.base import LLMServiceError
from backend.llm.mock_llm import MockLLMService, MockMode
from backend.schemas import (
    Executor,
    IntakeState,
    MessageRole,
)
from backend.state_manager import SessionManager, SessionNotFoundError


class TestConversationOrchestrator:
    @pytest.fixture
    def session_manager(self):
        return SessionManager()

    @pytest.fixture
    def mock_llm(self):
        return MockLLMService()

    @pytest.fixture
    def orchestrator(self, session_manager, mock_llm):
        return ConversationOrchestrator(session_manager=session_manager, llm_service=mock_llm)

    def test_1_simple_single_turn_extraction(self, orchestrator, session_manager):
        """Test 1: User provides name -> state updates with name, other fields remain None."""
        session = session_manager.create_session("test-s1")
        result = orchestrator.handle_user_message("test-s1", "My name is Karan Deshmukh")

        assert isinstance(result, OrchestratorResult)
        assert result.state.full_name == "Karan Deshmukh"
        assert result.state.home_address is None
        assert result.status == "in_progress"
        assert "address" in result.assistant_message.lower()

    def test_2_multi_turn_executor_conversation(self, orchestrator, session_manager):
        """
        Test 2: Multi-turn flow where executor name is provided in Turn 1,
        and relationship is supplied in Turn 2, preserving the name.
        """
        session_manager.create_session("test-s2")

        # Turn 1: User names executor
        turn_1 = orchestrator.handle_user_message("test-s2", "Rahul is my executor.")
        assert turn_1.state.executor.name == "Rahul"
        assert turn_1.state.executor.relationship is None
        assert "relationship" in turn_1.assistant_message.lower()

        # Turn 2: User states relationship
        turn_2 = orchestrator.handle_user_message("test-s2", "He is my brother")
        assert turn_2.state.executor.name == "Rahul"
        assert turn_2.state.executor.relationship == "Brother"
        assert turn_2.state.executor.is_complete

    def test_3_multi_field_extraction(self, orchestrator, session_manager):
        """Test 3: Single turn extracting multiple fields at once."""
        session_manager.create_session("test-s3")
        user_msg = (
            "My name is Karan Deshmukh, I live in Nagpur, I don't have children, "
            "and my brother Rahul is my executor."
        )
        result = orchestrator.handle_user_message("test-s3", user_msg)

        assert result.state.full_name == "Karan Deshmukh"
        assert result.state.home_address == "Nagpur"
        assert result.state.has_children is False
        assert result.state.children == []
        assert result.state.executor.name == "Rahul"
        assert result.state.executor.relationship == "Brother"
        assert result.status == "in_progress"

    def test_4_ambiguous_input(self, orchestrator, session_manager):
        """Test 4: Ambiguous message triggers clarification and blocks state change."""
        session_manager.create_session("test-s4")
        result = orchestrator.handle_user_message("test-s4", "I want everything covered.")

        assert result.status == "clarification_needed"
        assert result.state.covers_worldwide_assets is None
        assert result.pending_clarification is not None
        assert "worldwide" in result.assistant_message.lower()

    def test_5_contradictory_input(self, orchestrator, session_manager):
        """
        Test 5: Stating children when state already recorded has_children=False
        flags a contradiction and refuses state mutation.
        """
        session = session_manager.create_session("test-s5")
        session_manager.update_state("test-s5", IntakeState(has_children=False, children=[]))

        result = orchestrator.handle_user_message(
            "test-s5", "My daughter Ananya should receive my car."
        )

        assert result.status == "contradiction_detected"
        # State must NOT be mutated
        assert result.state.has_children is False
        assert result.state.children == []
        assert result.pending_clarification is not None
        assert result.pending_clarification.field_name == "has_children"
        assert "Notice:" in result.assistant_message

    def test_6_explicit_correction(self, orchestrator, session_manager):
        """Test 6: Correction updates target field while preserving unaffected attributes."""
        session_manager.create_session("test-s6")
        session_manager.update_state(
            "test-s6",
            IntakeState(
                full_name="Karan Deshmukh",
                executor=Executor(name="Rahul", relationship="Brother"),
            ),
        )

        result = orchestrator.handle_user_message(
            "test-s6", "Actually, change my executor to Amit."
        )

        assert result.state.executor.name == "Amit"
        assert result.state.executor.relationship == "Brother"
        assert result.status == "in_progress"

    def test_7_unknown_information_remains_unknown(self, orchestrator, session_manager):
        """Test 7: Partial executor never invents relationship."""
        session_manager.create_session("test-s7")
        result = orchestrator.handle_user_message("test-s7", "Rahul is my executor.")

        assert result.state.executor.name == "Rahul"
        assert result.state.executor.relationship is None
        assert result.state.covers_worldwide_assets is None
        assert result.state.has_children is None

    def test_8_off_topic_input(self, orchestrator, session_manager):
        """Test 8: Off-topic input leaves state unchanged and politely redirects user."""
        session_manager.create_session("test-s8")
        session_manager.update_state("test-s8", IntakeState(full_name="Karan"))

        result = orchestrator.handle_user_message("test-s8", "What is the weather today in London?")

        assert result.state.full_name == "Karan"
        assert "Personal Wishes Document" in result.assistant_message

    def test_9_malformed_llm_response(self, session_manager):
        """Test 9: Malformed LLM response is caught by boundary without crashing."""
        mock_llm = MockLLMService(mode=MockMode.MALFORMED_JSON)
        orchestrator = ConversationOrchestrator(session_manager, mock_llm)

        session_manager.create_session("test-s9")
        session_manager.update_state("test-s9", IntakeState(full_name="Karan"))

        result = orchestrator.handle_user_message("test-s9", "My address is Nagpur")

        assert result.status == "error"
        # State must remain intact
        assert result.state.full_name == "Karan"
        assert result.state.home_address is None
        assert "trouble processing" in result.assistant_message.lower()

    def test_10_llm_service_failure(self, session_manager):
        """Test 10: Generic LLMServiceError handled safely."""
        class FailingLLM(MockLLMService):
            def generate_response(self, user_message, current_state, history=None):
                raise LLMServiceError("Network timeout connecting to AI provider.")

        orchestrator = ConversationOrchestrator(session_manager, FailingLLM())
        session_manager.create_session("test-s10")
        session_manager.update_state("test-s10", IntakeState(full_name="Karan"))

        result = orchestrator.handle_user_message("test-s10", "Hello")
        assert result.status == "error"
        assert result.state.full_name == "Karan"
        assert "technical difficulties" in result.assistant_message.lower()

    def test_11_missing_session(self, orchestrator):
        """Test 11: Invoking message on a non-existent session raises SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError):
            orchestrator.handle_user_message("nonexistent-session", "Hello")

    def test_12_state_is_unchanged_after_validation_failure(self, orchestrator, session_manager):
        """Test 12: Contradiction or ambiguity preserves pristine prior state."""
        session_manager.create_session("test-s12")
        initial_state = IntakeState(
            full_name="Karan",
            home_address="Nagpur",
            has_children=False,
        )
        session_manager.update_state("test-s12", initial_state)

        # Trigger contradiction
        result = orchestrator.handle_user_message("test-s12", "My daughter Ananya...")

        assert result.status == "contradiction_detected"
        assert result.state.full_name == "Karan"
        assert result.state.home_address == "Nagpur"
        assert result.state.has_children is False
        assert result.state.children == []

    def test_13_state_is_unchanged_after_llm_failure(self, session_manager):
        """Test 13: Invalid schema mode preserves pristine state."""
        mock_llm = MockLLMService(mode=MockMode.INVALID_SCHEMA)
        orchestrator = ConversationOrchestrator(session_manager, mock_llm)

        session_manager.create_session("test-s13")
        initial_state = IntakeState(full_name="Karan")
        session_manager.update_state("test-s13", initial_state)

        result = orchestrator.handle_user_message("test-s13", "My address is Nagpur")

        assert result.status == "error"
        assert result.state.full_name == "Karan"
        assert result.state.home_address is None

    def test_14_user_and_assistant_messages_recorded_correctly(self, orchestrator, session_manager):
        """Test 14: Both user message and assistant reply are chronologically recorded in history."""
        session_manager.create_session("test-s14")

        orchestrator.handle_user_message("test-s14", "My name is Karan Deshmukh")
        orchestrator.handle_user_message("test-s14", "I live in Nagpur")

        session = session_manager.get_session("test-s14")
        history = session.conversation_history

        assert len(history) == 4
        assert history[0].role == MessageRole.USER
        assert history[0].content == "My name is Karan Deshmukh"
        assert history[1].role == MessageRole.ASSISTANT
        assert history[2].role == MessageRole.USER
        assert history[2].content == "I live in Nagpur"
        assert history[3].role == MessageRole.ASSISTANT

    def test_15_multiple_sessions_remain_isolated(self, orchestrator, session_manager):
        """Test 15: Actions in Session A do not leak into or alter Session B."""
        session_manager.create_session("session-A")
        session_manager.create_session("session-B")

        orchestrator.handle_user_message("session-A", "My name is Karan Deshmukh")
        orchestrator.handle_user_message("session-B", "My name is Rohit Sharma")

        state_A = session_manager.get_session("session-A").state
        state_B = session_manager.get_session("session-B").state

        assert state_A.full_name == "Karan Deshmukh"
        assert state_B.full_name == "Rohit Sharma"
        assert len(session_manager.get_session("session-A").conversation_history) == 2
        assert len(session_manager.get_session("session-B").conversation_history) == 2
