"""
Abstract base class for LLM service interaction.

Defines the contract that both MockLLMService and GeminiLLMService must fulfill.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from backend.schemas import ChatMessage, IntakeState, LLMResponse


class LLMServiceError(Exception):
    """Base exception for LLM service failures."""
    pass


class LLMMalformedResponseError(LLMServiceError):
    """Raised when the LLM returns an unparseable or schema-violating payload."""
    pass


class LLMService(ABC):
    """
    Abstract interface for LLM extraction and conversational turn generation.
    Decouples application logic and validation from the underlying AI model.
    """

    @abstractmethod
    def generate_response(
        self,
        user_message: str,
        current_state: IntakeState,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        """
        Processes a user message in context of current state and history,
        extracts candidate fields, classifies intent, and returns a typed LLMResponse.

        Raises:
            LLMMalformedResponseError: If the underlying model produces invalid output.
            LLMServiceError: If communication with the model fails.
        """
        pass
