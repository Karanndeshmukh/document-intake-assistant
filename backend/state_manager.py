"""
In-memory session manager for Document Intake Assistant.

Provides clean CRUD operations for SessionState instances.
Keeps conversation history and structured IntakeState strictly partitioned.
"""

from datetime import datetime, timezone
from typing import Dict, Optional
import uuid

from backend.schemas import (
    ChatMessage,
    IntakeState,
    MessageRole,
    PendingClarification,
    SessionState,
)


class SessionNotFoundError(Exception):
    """Raised when a session ID does not exist in memory."""
    pass


class SessionManager:
    """
    In-memory storage and lifecycle management for user intake sessions.
    Each session is isolated with its own unique session_id, IntakeState,
    conversation history, and optional pending clarification.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    def create_session(self, session_id: Optional[str] = None) -> SessionState:
        """
        Creates and stores a new isolated session with a clean IntakeState.
        """
        sid = session_id or str(uuid.uuid4())
        session = SessionState(session_id=sid)
        self._sessions[sid] = session
        return session

    def get_session(self, session_id: str) -> SessionState:
        """
        Retrieves an existing session by ID. Raises SessionNotFoundError if not found.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"Session '{session_id}' not found.")
        return self._sessions[session_id]

    def exists(self, session_id: str) -> bool:
        """Checks whether a session ID exists."""
        return session_id in self._sessions

    def update_state(self, session_id: str, new_state: IntakeState) -> SessionState:
        """
        Updates the structured IntakeState of a session.
        """
        session = self.get_session(session_id)
        session.state = new_state
        session.updated_at = datetime.now(timezone.utc)
        return session

    def add_message(self, session_id: str, role: MessageRole, content: str) -> ChatMessage:
        """
        Appends a message to the session's conversation history.
        """
        session = self.get_session(session_id)
        msg = ChatMessage(role=role, content=content)
        session.conversation_history.append(msg)
        session.updated_at = datetime.now(timezone.utc)
        return msg

    def set_pending_clarification(
        self, session_id: str, clarification: Optional[PendingClarification]
    ) -> SessionState:
        """
        Sets or clears a pending clarification on the session.
        """
        session = self.get_session(session_id)
        session.pending_clarification = clarification
        session.updated_at = datetime.now(timezone.utc)
        return session

    def reset_session(self, session_id: str) -> SessionState:
        """
        Resets an existing session to a blank state and empty history.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"Session '{session_id}' not found.")
        session = SessionState(session_id=session_id)
        self._sessions[session_id] = session
        return session

    def delete_session(self, session_id: str) -> None:
        """
        Deletes a session from memory.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

    def clear_all(self) -> None:
        """Clears all sessions in memory (useful for test tear-downs)."""
        self._sessions.clear()
