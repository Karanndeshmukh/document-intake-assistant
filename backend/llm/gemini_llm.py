"""
Google Gemini LLM Service implementation for Document Intake Assistant.

Interacts with the Google Gemini API using structured JSON output mode,
validating raw model output strictly through the Pydantic LLMResponse schema.
"""

import json
import re
from typing import List, Optional
import urllib.error
import urllib.request

from pydantic import ValidationError

from backend.config import settings
from backend.llm.base import LLMService, LLMServiceError, LLMMalformedResponseError
from backend.llm.prompts import SYSTEM_PROMPT, format_prompt_context
from backend.schemas import ChatMessage, IntakeState, LLMResponse


class GeminiLLMService(LLMService):
    """
    LLMService implementation powered by Google Gemini.
    Requests structured JSON and returns strongly typed LLMResponse objects.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL or "gemini-2.5-flash"

        if not self.api_key:
            raise LLMServiceError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in your .env file."
            )

    def generate_response(
        self,
        user_message: str,
        current_state: IntakeState,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        """
        Sends conversation state, history, and user utterance to Gemini,
        requesting a structured JSON extraction according to the schema.
        """
        prompt_content = format_prompt_context(
            current_state=current_state,
            history=history,
            user_message=user_message,
        )

        raw_response_text = self._call_gemini_api(prompt_content)
        return self._parse_and_validate_response(raw_response_text)

    def _call_gemini_api(self, prompt_text: str) -> str:
        """
        Executes HTTP POST to Google Gemini generateContent endpoint.
        """
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent"
        )

        payload = {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "enum": ["inform", "correction", "ambiguous", "contradiction", "off_topic"]},
                        "extracted_fields": {"type": "object"},
                        "ambiguity_reason": {"type": "string", "nullable": True},
                        "contradiction_reason": {"type": "string", "nullable": True},
                        "assistant_reply": {"type": "string"}
                    },
                    "required": ["intent", "assistant_reply"]
                }
            },
        }

        request_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=request_data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30.0) as response:
                response_body = response.read().decode("utf-8")
                response_json = json.loads(response_body)
                
                # Extract text content from Gemini response structure
                candidates = response_json.get("candidates", [])
                if not candidates:
                    raise LLMServiceError("Gemini returned an empty response with no candidates.")
                
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    raise LLMServiceError("Gemini candidate contains no content parts.")
                
                return parts[0].get("text", "")

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise LLMServiceError(f"Gemini API HTTP {e.code} Error: {error_body}") from e
        except urllib.error.URLError as e:
            raise LLMServiceError(f"Network failure connecting to Gemini API: {str(e)}") from e
        except TimeoutError as e:
            raise LLMServiceError("Gemini API request timed out.") from e
        except Exception as e:
            if isinstance(e, (LLMServiceError, LLMMalformedResponseError)):
                raise e
            raise LLMServiceError(f"Unexpected error communicating with Gemini: {str(e)}") from e

    def _parse_and_validate_response(self, raw_text: str) -> LLMResponse:
        """
        Parses JSON output from Gemini and strictly validates it through Pydantic.
        """
        cleaned_text = raw_text.strip()
        # Remove potential markdown markdown fence wrapping e.g. ```json ... ```
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```(?:json)?\n?", "", cleaned_text)
            cleaned_text = re.sub(r"\n?```$", "", cleaned_text).strip()

        try:
            payload_dict = json.loads(cleaned_text)
            return LLMResponse.model_validate(payload_dict)
        except json.JSONDecodeError as e:
            raise LLMMalformedResponseError(
                f"Gemini output is not valid JSON: {str(e)} | Raw: {raw_text[:200]}"
            ) from e
        except ValidationError as e:
            raise LLMMalformedResponseError(
                f"Gemini output failed schema validation: {str(e)}"
            ) from e
        except Exception as e:
            raise LLMMalformedResponseError(
                f"Failed to parse Gemini response: {str(e)}"
            ) from e
