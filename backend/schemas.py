"""
Data schemas for Document Intake Assistant.

This module defines all Pydantic schemas across four distinct boundaries:
1. Structured State (IntakeState, Executor, SpecificGift) - single source of truth
2. Typed LLM Extraction (LLMResponse, ExtractedFields, IntentType)
3. Session Model (SessionState, ChatMessage, PendingClarification)
4. API Contracts (ChatRequest, ChatResponse, SessionInitResponse, etc.)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Any
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================================
# 1. STRUCTURED STATE SCHEMAS (Source of Truth for Personal Wishes)
# ============================================================================

class Executor(BaseModel):
    """
    Executor details. Unknown fields MUST remain None.
    Never assume relationship if only name is provided.
    """
    name: Optional[str] = None
    relationship: Optional[str] = None

    @field_validator("name", "relationship", mode="before")
    @classmethod
    def clean_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        return v_str if v_str else None

    @property
    def is_complete(self) -> bool:
        return bool(self.name and self.relationship)

    @property
    def is_empty(self) -> bool:
        return self.name is None and self.relationship is None


class SpecificGift(BaseModel):
    """
    Specific item or monetary gift designated to a specific recipient.
    """
    recipient: str = Field(..., min_length=1, description="Recipient name/identity")
    item_or_amount: str = Field(..., min_length=1, description="Description of the item or monetary sum")

    @field_validator("recipient", "item_or_amount", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Gift fields cannot be empty")
        v_str = str(v).strip()
        if not v_str:
            raise ValueError("Gift fields cannot be blank")
        return v_str


class IntakeState(BaseModel):
    """
    The structured state representing the user's Personal Wishes document.
    Unknown values must remain None / empty list.
    The system must never invent missing information.
    """
    full_name: Optional[str] = None
    home_address: Optional[str] = None
    covers_worldwide_assets: Optional[bool] = None
    has_children: Optional[bool] = None
    children: List[str] = Field(default_factory=list)
    executor: Executor = Field(default_factory=Executor)
    specific_gifts: List[SpecificGift] = Field(default_factory=list)
    additional_wishes: Optional[str] = None

    @field_validator("full_name", "home_address", "additional_wishes", mode="before")
    @classmethod
    def clean_optional_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        return v_str if v_str else None

    @field_validator("children", mode="before")
    @classmethod
    def clean_children_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            cleaned = []
            for item in v:
                if item is not None:
                    s = str(item).strip()
                    if s and s not in cleaned:
                        cleaned.append(s)
            return cleaned
        return []

    @model_validator(mode="after")
    def validate_children_consistency(self) -> "IntakeState":
        # If user explicitly states they do not have children, children list must be empty
        if self.has_children is False and len(self.children) > 0:
            raise ValueError("Children list must be empty when has_children is False")
        # If children are present, has_children should logically be True
        if len(self.children) > 0 and self.has_children is None:
            self.has_children = True
        return self

    def get_missing_fields(self) -> List[str]:
        """
        Returns a human-readable list of required document intake fields that
        are currently unknown.
        """
        missing = []
        if not self.full_name:
            missing.append("full_name")
        if not self.home_address:
            missing.append("home_address")
        if self.covers_worldwide_assets is None:
            missing.append("covers_worldwide_assets")
        if self.has_children is None:
            missing.append("has_children")
        elif self.has_children is True and len(self.children) == 0:
            missing.append("children_names")
        if not self.executor.name:
            missing.append("executor_name")
        if not self.executor.relationship:
            missing.append("executor_relationship")
        return missing

    @property
    def is_complete(self) -> bool:
        """
        A state is complete when all mandatory primary fields are captured.
        (Specific gifts and additional wishes are optional wishes).
        """
        return len(self.get_missing_fields()) == 0


# ============================================================================
# 2. TYPED LLM RESPONSE SCHEMAS (LLM Extraction Contract)
# ============================================================================

class IntentType(str, Enum):
    INFORM = "inform"              # Normal information provision
    CORRECTION = "correction"      # Explicit correction of a previously stated field
    AMBIGUOUS = "ambiguous"        # Ambiguous user statement requiring clarification
    CONTRADICTION = "contradiction"# Statement directly conflicting with established state
    OFF_TOPIC = "off_topic"        # Chit-chat or unrelated request


class ExtractedFields(BaseModel):
    """
    Strongly typed container for any fields the LLM extracted from the user's turn.
    Only fields present in the current turn are populated; others remain None.
    """
    full_name: Optional[str] = None
    home_address: Optional[str] = None
    covers_worldwide_assets: Optional[bool] = None
    has_children: Optional[bool] = None
    children: Optional[List[str]] = None
    executor: Optional[Executor] = None
    specific_gifts: Optional[List[SpecificGift]] = None
    additional_wishes: Optional[str] = None

    @field_validator("full_name", "home_address", "additional_wishes", mode="before")
    @classmethod
    def clean_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        return v_str if v_str else None


class LLMResponse(BaseModel):
    """
    The structured response contract returned by LLMService (Mock or Real Gemini).
    The application receives this strongly typed object and decides on state mutations.
    """
    intent: IntentType = IntentType.INFORM
    extracted_fields: ExtractedFields = Field(default_factory=ExtractedFields)
    ambiguity_reason: Optional[str] = None
    contradiction_reason: Optional[str] = None
    assistant_reply: str = Field(..., min_length=1, description="Conversational reply to display")


# ============================================================================
# 3. SESSION SCHEMAS (Simple, non-event-sourced session model)
# ============================================================================

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    """
    Single message in the conversation history.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingClarification(BaseModel):
    """
    Temporary holder when a contradiction or ambiguity is flagged and awaiting resolution.
    """
    field_name: str
    reason: str
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None


class SessionState(BaseModel):
    """
    Top-level session container holding state, history, and active clarification info.
    """
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    state: IntakeState = Field(default_factory=IntakeState)
    conversation_history: List[ChatMessage] = Field(default_factory=list)
    pending_clarification: Optional[PendingClarification] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# 4. API REQUEST / RESPONSE SCHEMAS (REST Interface Contracts)
# ============================================================================

class SessionInitResponse(BaseModel):
    session_id: str
    state: IntakeState
    initial_message: str
    draft_document: str = ""


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, description="User's input message")

    @field_validator("message", mode="before")
    @classmethod
    def clean_message(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Message cannot be empty")
        v_str = str(v).strip()
        if not v_str:
            raise ValueError("Message cannot be empty whitespace")
        return v_str


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    state: IntakeState
    draft_document: str
    missing_fields: List[str]
    status: str = Field(
        default="in_progress",
        description="'in_progress', 'clarification_needed', 'contradiction_detected', 'complete', or 'error'"
    )
    pending_clarification: Optional[PendingClarification] = None


class StateResponse(BaseModel):
    session_id: str
    state: IntakeState
    missing_fields: List[str]
    is_complete: bool


class DocumentResponse(BaseModel):
    session_id: str
    document: str
    is_complete: bool
