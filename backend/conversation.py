"""
Conversation orchestrator for Document Intake Assistant.

Mediates between the SessionManager, LLMService, and ValidationEngine.
Guarantees transactional state safety: IntakeState is never updated until
LLM extraction successfully passes deterministic validation rules.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from backend.document_generator import DocumentGenerator
from backend.llm.base import LLMService, LLMServiceError, LLMMalformedResponseError
from backend.schemas import (
    IntakeState,
    MessageRole,
    PendingClarification,
)
from backend.state_manager import SessionManager, SessionNotFoundError
from backend.validation import ValidationEngine, ValidationStatus


class OrchestratorResult(BaseModel):
    """
    Structured outcome returned by the ConversationOrchestrator for a single user turn.
    Directly maps to the API layer's ChatResponse payload.
    """
    session_id: str
    assistant_message: str
    state: IntakeState
    missing_fields: List[str]
    status: str = Field(
        ...,
        description="'in_progress', 'clarification_needed', 'contradiction_detected', 'complete', or 'error'",
    )
    draft_document: str = ""
    pending_clarification: Optional[PendingClarification] = None


class ConversationOrchestrator:
    """
    Orchestrates multi-turn dialogue, coordinating LLM extraction, deterministic
    validation, session persistence, and conflict/clarification tracking.
    """

    def __init__(self, session_manager: SessionManager, llm_service: LLMService) -> None:
        self.session_manager = session_manager
        self.llm_service = llm_service

    def handle_user_message(self, session_id: str, user_message: str) -> OrchestratorResult:
        """
        Executes a single conversational turn through the safe transactional pipeline:
        1. Retrieve session & current state.
        2. Record user message in history.
        3. Invoke LLMService to extract candidate fields and classify intent.
        4. Pass candidates to ValidationEngine.
        5. Atomically commit state update if valid.
        6. Generate updated draft document from confirmed state.
        7. Record assistant reply and return result.
        """
        # Step 1: Session Verification
        session = self.session_manager.get_session(session_id)
        current_state = session.state

        # Step 2: Record User Message in History
        self.session_manager.add_message(session_id, MessageRole.USER, user_message)

        # Step 3: LLM Extraction & Intent Classification (Protected by Error Boundary)
        try:
            llm_response = self.llm_service.generate_response(
                user_message=user_message,
                current_state=current_state,
                history=session.conversation_history,
            )
        except LLMMalformedResponseError as e:
            error_reply = (
                "I apologize, but I had trouble processing your response properly. "
                "Could you please rephrase or state your answer again?"
            )
            self.session_manager.add_message(session_id, MessageRole.ASSISTANT, error_reply)
            return OrchestratorResult(
                session_id=session_id,
                assistant_message=error_reply,
                state=current_state,
                missing_fields=current_state.get_missing_fields(),
                status="error",
                draft_document=DocumentGenerator.generate(current_state),
                pending_clarification=session.pending_clarification,
            )
        except LLMServiceError as e:
            error_reply = (
                "The assistant is currently experiencing technical difficulties. "
                "Your information is safe, please try sending your message again."
            )
            self.session_manager.add_message(session_id, MessageRole.ASSISTANT, error_reply)
            return OrchestratorResult(
                session_id=session_id,
                assistant_message=error_reply,
                state=current_state,
                missing_fields=current_state.get_missing_fields(),
                status="error",
                draft_document=DocumentGenerator.generate(current_state),
                pending_clarification=session.pending_clarification,
            )
        except Exception as e:
            error_reply = (
                "An unexpected error occurred while processing your request. "
                "Please try again."
            )
            self.session_manager.add_message(session_id, MessageRole.ASSISTANT, error_reply)
            return OrchestratorResult(
                session_id=session_id,
                assistant_message=error_reply,
                state=current_state,
                missing_fields=current_state.get_missing_fields(),
                status="error",
                draft_document=DocumentGenerator.generate(current_state),
                pending_clarification=session.pending_clarification,
            )

        # Step 4: Deterministic Validation
        validation_result = ValidationEngine.validate_and_apply(
            current_state=current_state,
            extracted=llm_response.extracted_fields,
            intent=llm_response.intent,
            ambiguity_reason=llm_response.ambiguity_reason,
            contradiction_reason=llm_response.contradiction_reason,
        )

        # Step 5: State Transition and Clarification Management
        assistant_reply = llm_response.assistant_reply

        if validation_result.status in (ValidationStatus.APPLIED, ValidationStatus.CORRECTED):
            # Commit state update to SessionManager
            self.session_manager.update_state(session_id, validation_result.updated_state)
            
            # Clear pending clarification if it existed
            if session.pending_clarification:
                self.session_manager.set_pending_clarification(session_id, None)

            current_state = validation_result.updated_state
            status = "complete" if current_state.is_complete else "in_progress"

        elif validation_result.status == ValidationStatus.CONTRADICTION:
            # Block state mutation; record contradiction on session
            self.session_manager.set_pending_clarification(
                session_id, validation_result.pending_clarification
            )
            status = "contradiction_detected"
            if validation_result.pending_clarification:
                assistant_reply = (
                    f"Notice: {validation_result.pending_clarification.reason} "
                    f"Could you please clarify your wishes?"
                )

        elif validation_result.status == ValidationStatus.AMBIGUOUS:
            # Block state mutation; record ambiguity on session
            self.session_manager.set_pending_clarification(
                session_id, validation_result.pending_clarification
            )
            status = "clarification_needed"

        elif validation_result.status == ValidationStatus.INVALID:
            status = "in_progress"
            assistant_reply = (
                "I wasn't able to process that update because it conflicted with standard guidelines. "
                "Could you please restate that detail?"
            )

        else:  # NO_OP or OFF_TOPIC
            status = "complete" if current_state.is_complete else "in_progress"

        # Step 6: Record Assistant Reply and Return OrchestratorResult
        self.session_manager.add_message(session_id, MessageRole.ASSISTANT, assistant_reply)

        updated_session = self.session_manager.get_session(session_id)

        return OrchestratorResult(
            session_id=session_id,
            assistant_message=assistant_reply,
            state=updated_session.state,
            missing_fields=updated_session.state.get_missing_fields(),
            status=status,
            draft_document=DocumentGenerator.generate(updated_session.state),
            pending_clarification=updated_session.pending_clarification,
        )
