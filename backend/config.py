"""
Configuration management for Document Intake Assistant.

Loads application settings and environment variables securely from .env.
Never hard-codes API keys or secrets.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


class Settings:
    """Application configuration settings."""

    # LLM Provider: 'mock' or 'gemini'
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    # Google Gemini Configuration
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", "").strip() or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    # Server Configuration
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))


settings = Settings()
