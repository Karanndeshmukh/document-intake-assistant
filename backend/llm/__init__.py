"""
LLM abstraction package for Document Intake Assistant.
"""

from backend.llm.base import LLMService, LLMServiceError, LLMMalformedResponseError
from backend.llm.factory import get_llm_service, LLMConfigurationError
from backend.llm.gemini_llm import GeminiLLMService
from backend.llm.mock_llm import MockLLMService

__all__ = [
    "LLMService",
    "LLMServiceError",
    "LLMMalformedResponseError",
    "LLMConfigurationError",
    "MockLLMService",
    "GeminiLLMService",
    "get_llm_service",
]
