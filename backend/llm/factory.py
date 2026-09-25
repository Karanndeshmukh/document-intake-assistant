"""
LLM Provider Factory for Document Intake Assistant.

Constructs and returns the configured LLMService implementation ('mock' or 'gemini').
Prevents silent fallback when a specific provider was explicitly configured.
"""

from typing import Optional

from backend.config import settings
from backend.llm.base import LLMService, LLMServiceError
from backend.llm.gemini_llm import GeminiLLMService
from backend.llm.mock_llm import MockLLMService


class LLMConfigurationError(LLMServiceError):
    """Raised when the configured LLM provider has invalid or missing settings."""
    pass


def get_llm_service(provider: Optional[str] = None) -> LLMService:
    """
    Factory function to instantiate the active LLMService.

    Args:
        provider: Optional explicit provider override ('mock' or 'gemini').
                  Defaults to settings.LLM_PROVIDER.

    Returns:
        LLMService instance (MockLLMService or GeminiLLMService).

    Raises:
        LLMConfigurationError: If the provider is unknown or missing required credentials.
    """
    selected = (provider or settings.LLM_PROVIDER or "mock").strip().lower()

    if selected == "mock":
        return MockLLMService()

    elif selected == "gemini":
        if not settings.GEMINI_API_KEY:
            raise LLMConfigurationError(
                "LLM_PROVIDER is set to 'gemini', but GEMINI_API_KEY is not set in environment or .env file."
            )
        return GeminiLLMService(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.GEMINI_MODEL,
        )

    else:
        raise LLMConfigurationError(
            f"Unsupported LLM_PROVIDER '{selected}'. Supported providers are: 'mock', 'gemini'."
        )
