"""
Unit tests for SessionManager.

Tests cover:
- Creating a session
- Retrieving a session
- Updating a session state
- Session history and message tracking
- Pending clarification management
- Session isolation (sessions do not interfere with each other)
"""

import pytest

from backend.schemas import (
    Executor,
    IntakeState,
    MessageRole,
    PendingClarification,
)
from backend.state_manager import SessionManager, SessionNotFoundError


class TestSessionManager:
    @pytest.fixture
    def manager(self):
        return SessionManager()

    def test_create_and_get_session(self, manager):
        """Test A & B: Creating a session generates an isolated IntakeState and can be retrieved."""
        session = manager.create_session("session-1")
        assert session.session_id == "session-1"
        assert session.state.full_name is None
        assert session.conversation_history == []

        retrieved = manager.get_session("session-1")
        assert retrieved.session_id == session.session_id

    def test_get_nonexistent_session_raises(self, manager):
        """Retrieving an unknown session raises SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError):
            manager.get_session("nonexistent-id")

    def test_update_session_state(self, manager):
        """Test C: Updating session state updates the stored IntakeState."""
        manager.create_session("session-1")
        new_state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        updated = manager.update_state("session-1", new_state)
        assert updated.state.full_name == "Karan Deshmukh"
        assert updated.state.executor.name == "Rahul"

    def test_add_message_to_history(self, manager):
        """Conversation messages append to conversation_history without modifying state."""
        manager.create_session("session-1")
        msg = manager.add_message("session-1", MessageRole.USER, "My name is Karan")
        assert msg.role == MessageRole.USER
        assert msg.content == "My name is Karan"

        session = manager.get_session("session-1")
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0].content == "My name is Karan"
        # State must remain untouched by raw message logging
        assert session.state.full_name is None

    def test_set_pending_clarification(self, manager):
        """Setting and clearing pending clarification updates the session."""
        manager.create_session("session-1")
        clarification = PendingClarification(
            field_name="has_children",
            reason="Contradiction between no children and daughter Ananya",
        )
        session = manager.set_pending_clarification("session-1", clarification)
        assert session.pending_clarification is not None
        assert session.pending_clarification.field_name == "has_children"

        # Clear clarification
        session = manager.set_pending_clarification("session-1", None)
        assert session.pending_clarification is None

    def test_session_isolation(self, manager):
        """Test L: Operations on session-1 must never affect session-2."""
        s1 = manager.create_session("session-1")
        s2 = manager.create_session("session-2")

        manager.update_state("session-1", IntakeState(full_name="User One"))
        manager.add_message("session-1", MessageRole.USER, "Hello from Session 1")

        # Session 2 must remain completely pristine and unaffected
        s2_fresh = manager.get_session("session-2")
        assert s2_fresh.state.full_name is None
        assert len(s2_fresh.conversation_history) == 0

    def test_reset_session(self, manager):
        """Resetting a session clears state and history while retaining ID."""
        manager.create_session("session-1")
        manager.update_state("session-1", IntakeState(full_name="Karan"))
        manager.add_message("session-1", MessageRole.USER, "Hi")

        reset = manager.reset_session("session-1")
        assert reset.session_id == "session-1"
        assert reset.state.full_name is None
        assert len(reset.conversation_history) == 0
