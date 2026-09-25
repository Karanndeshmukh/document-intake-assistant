"""
Deterministic Mock LLM Service for Document Intake Assistant.

Simulates LLM extraction, intent classification, and conversational follow-ups
without external API dependencies. This component simulates what an LLM produces,
leaving all state mutation decisions to the deterministic ValidationEngine.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from backend.llm.base import LLMService, LLMMalformedResponseError
from backend.schemas import (
    ChatMessage,
    Executor,
    ExtractedFields,
    IntakeState,
    IntentType,
    LLMResponse,
    MessageRole,
    SpecificGift,
)


# ---------------------------------------------------------------------------
# Relationship vocabulary (reused in multiple patterns)
# ---------------------------------------------------------------------------
_RELATIONSHIPS = (
    "brother", "sister", "spouse", "wife", "husband", "friend", "lawyer",
    "son", "daughter", "cousin", "father", "mother",
)
_REL_ALT = "|".join(_RELATIONSHIPS)


class MockMode(str, Enum):
    """Modes to simulate normal operation and fault boundaries."""
    NORMAL = "normal"
    MALFORMED_JSON = "malformed_json"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_ENUM = "invalid_enum"
    INVALID_TYPES = "invalid_types"


class MockLLMService(LLMService):
    """
    Simulates an LLM extraction and dialogue engine.
    Uses pattern heuristics to populate typed ExtractedFields and classify IntentType.
    """

    def __init__(self, mode: MockMode = MockMode.NORMAL) -> None:
        self.mode = mode

    def set_mode(self, mode: MockMode) -> None:
        """Configures the mock simulation mode for testing error boundaries."""
        self.mode = mode

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_response(
        self,
        user_message: str,
        current_state: IntakeState,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        """
        Processes user input and produces a typed LLMResponse.
        Simulates model output or raises errors according to the active MockMode.
        """
        # Test Boundary: Simulate Malformed Raw Responses
        if self.mode != MockMode.NORMAL:
            raw_payload = self._generate_malformed_payload(self.mode)
            try:
                return LLMResponse.model_validate(raw_payload)
            except (ValidationError, TypeError) as e:
                raise LLMMalformedResponseError(f"Model returned invalid schema: {str(e)}") from e

        # Normal Deterministic Extraction
        return self._simulate_extraction(user_message, current_state, history=history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_malformed_payload(self, mode: MockMode) -> Dict[str, Any]:
        """Generates deliberately broken payloads to test boundary validation."""
        if mode == MockMode.MALFORMED_JSON:
            raise LLMMalformedResponseError("Failed to parse LLM response: Invalid JSON syntax.")
        elif mode == MockMode.INVALID_SCHEMA:
            # Missing mandatory 'assistant_reply'
            return {"intent": "inform", "extracted_fields": {}}
        elif mode == MockMode.INVALID_ENUM:
            return {
                "intent": "non_existent_intent_type",
                "assistant_reply": "I am confused.",
                "extracted_fields": {},
            }
        elif mode == MockMode.INVALID_TYPES:
            return {
                "intent": "inform",
                "assistant_reply": "Got it.",
                "extracted_fields": {"covers_worldwide_assets": "not_a_boolean_or_number"},
            }
        return {}

    @staticmethod
    def _last_assistant_content(history: Optional[List[ChatMessage]]) -> str:
        """Returns the content of the most-recent assistant message, or ''."""
        if not history:
            return ""
        for m in reversed(history):
            role = getattr(m, "role", None)
            if (
                role == MessageRole.ASSISTANT
                or role == "assistant"
                or str(role).lower() == "assistant"
            ):
                return getattr(m, "content", "") or ""
        return ""

    @staticmethod
    def _asking(content: str, keywords: str) -> bool:
        """True if the assistant message contains any of the given keyword alternatives."""
        return bool(re.search(keywords, content, re.IGNORECASE))

    def _simulate_extraction(
        self,
        user_message: str,
        current_state: IntakeState,
        history: Optional[List[ChatMessage]] = None,
    ) -> LLMResponse:
        """
        Parses the user message using deterministic pattern matching and
        constructs a candidate ExtractedFields payload and IntentType.
        """
        msg = user_message.strip()
        msg_lower = msg.lower()

        last_asst = self._last_assistant_content(history)

        # ------------------------------------------------------------------
        # 1. Off-topic check
        # ------------------------------------------------------------------
        off_topic_patterns = [
            r"\b(weather|temperature|forecast)\b",
            r"\b(recipe|cook|bake)\b",
            r"\b(capital of|who won|football score|joke)\b",
            r"\b(how are you|who created you|tell me a story|happy birthday|good morning|hello world)\b",
        ]
        for pattern in off_topic_patterns:
            if re.search(pattern, msg_lower):
                return LLMResponse(
                    intent=IntentType.OFF_TOPIC,
                    assistant_reply=(
                        "I am your Document Intake Assistant for preparing your Personal Wishes Document. "
                        "Let's focus on gathering the necessary details for your document."
                    ),
                )

        # ------------------------------------------------------------------
        # 2. Ambiguity check
        # ------------------------------------------------------------------
        ambiguous_patterns = [
            r"\bi want everything covered\b",
            r"\bcover everything\b",
            r"\ball my stuff everywhere\b",
            r"\bjust take care of it all\b",
        ]
        for pattern in ambiguous_patterns:
            if re.search(pattern, msg_lower):
                return LLMResponse(
                    intent=IntentType.AMBIGUOUS,
                    ambiguity_reason=(
                        "The statement 'everything covered' is ambiguous. It is unclear whether you mean "
                        "assets situated worldwide across all jurisdictions, or all asset classes in your home jurisdiction."
                    ),
                    assistant_reply=(
                        "To make sure your document is precise: by 'everything', do you mean assets located "
                        "worldwide across all countries, or all assets within your primary country of residence?"
                    ),
                )

        # ------------------------------------------------------------------
        # 3. Explicit Correction check
        # ------------------------------------------------------------------
        is_correction = bool(
            re.search(r"\b(actually|correction|change|instead of|replace|mistake|update my)\b", msg_lower)
        )

        extracted = ExtractedFields()
        extracted_labels: List[str] = []

        # ------------------------------------------------------------------
        # A. Full Name Extraction
        # ------------------------------------------------------------------
        # Context flag: are we being asked for the name right now?
        is_asking_name = False
        if current_state.full_name is None:
            if last_asst:
                if self._asking(last_asst, r"\b(name|legal name|full name)\b"):
                    is_asking_name = True
            else:
                # First turn / no history → opening greeting always asks for name
                is_asking_name = True

        name_match = re.search(
            r"(?:my name is|i am|name is|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)(?=\s*(?:,|;|\.|\b(?:and|i\s+live|living|from|with)\b|$))",
            msg,
            re.IGNORECASE,
        )
        if not name_match:
            name_match = re.search(
                r"(?:my name is|i am|name is|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
                msg,
                re.IGNORECASE,
            )
        if name_match:
            extracted.full_name = name_match.group(1).strip()
            extracted_labels.append("name")
        elif is_asking_name:
            _non_name = {
                "hello", "hi", "hey", "yes", "no", "ok", "okay", "sure", "help",
                "start", "none", "nothing", "skip", "idk", "why", "what", "how",
                "who", "where", "please", "thanks", "thank you", "actually",
            }
            cleaned = msg.strip().rstrip(".").strip()
            words = cleaned.split()
            if 1 <= len(words) <= 4:
                if not any(w.lower() in _non_name for w in words):
                    if all(re.match(r"^[A-Za-z]+(?:['\-][A-Za-z]+)?$", w) for w in words):
                        extracted.full_name = " ".join(w.capitalize() for w in words)
                        extracted_labels.append("name")

        # ------------------------------------------------------------------
        # B. Home Address Extraction
        # ------------------------------------------------------------------
        addr_match = re.search(
            r"(?:i live in|i live at|living in|home address is|my address is|address is|residing in)\s+([^;\n]+?)(?=\s*(?:\.|$|\n|;\s*|,\s*(?:and\s+)?(?:i\s+don't|i\s+have|my\s+brother|my\s+executor|my\s+sister)))",
            msg,
            re.IGNORECASE,
        )
        if not addr_match:
            addr_match = re.search(
                r"(?:i live in|i live at|living in|home address is|my address is|address is|residing in)\s+([^\n.]+)",
                msg,
                re.IGNORECASE,
            )
        if addr_match:
            extracted.home_address = addr_match.group(1).strip()
            extracted_labels.append("address")
        elif current_state.home_address is None and not extracted.full_name:
            # Context-aware fallback: treat concise reply as address when asked
            if self._asking(last_asst, r"\b(address|residential|home address|current address|where do you live)\b"):
                _non_addr = {
                    "yes", "no", "ok", "okay", "sure", "hello", "hi", "hey",
                    "help", "skip", "none", "nothing", "idk", "please",
                    "thanks", "thank you", "actually", "brother", "sister",
                    "spouse", "friend",
                }
                cleaned_addr = msg.strip().rstrip(".").strip()
                addr_words = cleaned_addr.split()
                if 1 <= len(addr_words) <= 10 and cleaned_addr:
                    if not any(w.lower() in _non_addr for w in addr_words[:2]):
                        extracted.home_address = cleaned_addr
                        extracted_labels.append("address")

        # ------------------------------------------------------------------
        # C. Worldwide Assets Extraction
        # ------------------------------------------------------------------
        # Explicit negative patterns (checked first to avoid false-positives)
        _neg_worldwide = re.compile(
            r"\b("
            r"not\s+worldwide"
            r"|no[,\s]+(?:not\s+worldwide|worldwide)"
            r"|(?:no[,\s]+)?(?:only|just)\s+(?:in\s+)?(?:my\s+|the\s+)?(?:home\s+country|country|india|locally|domestic|[a-z]+)"
            r"|(?:home\s+country|country|domestic|local|india)\s+only"
            r"|(?:in\s+)?(?:my\s+)?home\s+country"
            r"|domestic\s+only"
            r"|only\s+locally"
            r")\b",
            re.IGNORECASE,
        )
        _pos_worldwide = re.compile(
            r"\b(worldwide|all countries|globally|across the world|all\s+(?:my\s+)?assets\s+worldwide|all\s+over\s+the\s+world)\b",
            re.IGNORECASE,
        )
        # Context flag: are we being asked about worldwide assets?
        _asking_worldwide = self._asking(
            last_asst,
            r"\b(worldwide|all countries|assets outside|home country|asset jurisdiction|globally)\b",
        )
        _plain_yes = bool(re.search(r"^(?:yes|yeah|yep|sure|correct)\b", msg_lower))
        _plain_no  = bool(re.search(r"^(?:no|nope|nah)\b", msg_lower))

        if _neg_worldwide.search(msg_lower):
            extracted.covers_worldwide_assets = False
            extracted_labels.append("worldwide coverage (no)")
        elif _pos_worldwide.search(msg_lower):
            extracted.covers_worldwide_assets = True
            extracted_labels.append("worldwide coverage (yes)")
        elif current_state.covers_worldwide_assets is None and _asking_worldwide:
            # Context-aware: plain yes/no when the conversation is on this topic
            if _plain_yes:
                extracted.covers_worldwide_assets = True
                extracted_labels.append("worldwide coverage (yes)")
            elif _plain_no:
                extracted.covers_worldwide_assets = False
                extracted_labels.append("worldwide coverage (no)")
        elif current_state.covers_worldwide_assets is None and _plain_yes:
            # Fallback for when history is empty but state implies we should be asking worldwide
            if current_state.home_address is not None and current_state.full_name is not None:
                extracted.covers_worldwide_assets = True
                extracted_labels.append("worldwide coverage (yes)")

        # ------------------------------------------------------------------
        # D. Children Extraction
        # ------------------------------------------------------------------
        _asking_children = self._asking(last_asst, r"\b(children|kids|child|dependents)\b")
        _asking_children_names = self._asking(last_asst, r"\b(names? of|full names?)\b.*\b(children|kids)\b|\b(children|kids)\b.*\b(names?|full names?)\b")

        # Explicit negative
        if re.search(
            r"\b(don't have children|do not have children|no children|no kids|have no child"
            r"|i don't have any children|i do not have any children"
            r"|i have no children|i have no kids)\b",
            msg_lower,
        ):
            extracted.has_children = False
            extracted.children = []
            extracted_labels.append("children status (no children)")
        elif _asking_children and _plain_no:
            # Context-aware: "no" when asked about children
            extracted.has_children = False
            extracted.children = []
            extracted_labels.append("children status (no children)")
        else:
            # Try to find listed children names
            kids_match = re.search(
                r"(?:have\s+(?:\d+|a|one|two|three|four)?\s*(?:children|kids|child|daughter|son)s?(?::|\s+named|\s+called)?\s*)([A-Z][a-z]+(?:\s*(?:and|,)\s*[A-Z][a-z]+)*)",
                msg,
                re.IGNORECASE,
            )
            daughter_match = re.search(
                r"(?:my\s+daughter|my\s+son|my\s+child)\s+([A-Z][a-z]+)",
                msg,
                re.IGNORECASE,
            )
            # Comma/and-separated names when asked for children names explicitly
            bare_names_match = None
            if _asking_children_names and current_state.has_children is True:
                bare_names_match = re.search(
                    r"^([A-Z][a-z]+(?:\s*(?:and|,)\s*[A-Z][a-z]+)+)$",
                    msg.strip(),
                    re.IGNORECASE,
                )

            if kids_match:
                kids_raw = kids_match.group(1)
                names = [k.strip() for k in re.split(r",|\band\b", kids_raw) if k.strip()]
                extracted.has_children = True
                extracted.children = names
                extracted_labels.append("children")
            elif daughter_match:
                extracted.has_children = True
                extracted.children = [daughter_match.group(1).strip()]
                extracted_labels.append("children")
            elif bare_names_match:
                kids_raw = bare_names_match.group(1)
                names = [k.strip() for k in re.split(r",|\band\b", kids_raw) if k.strip()]
                extracted.has_children = True
                extracted.children = names
                extracted_labels.append("children names")
            elif _asking_children and _plain_yes:
                # Context-aware: "yes" when asked about children — set flag, don't invent names
                extracted.has_children = True
                extracted_labels.append("children status (has children)")

        # ------------------------------------------------------------------
        # E. Executor Extraction
        # ------------------------------------------------------------------
        _asking_exec_name = self._asking(
            last_asst,
            r"\b(executor|appoint|who would you like|executor.s name)\b",
        )
        _asking_exec_rel = self._asking(
            last_asst,
            r"\b(relationship|relation to you|relation to the executor)\b",
        )

        # Case 1: "my [rel] [Name] (is/will be) my executor"
        # Negative lookahead (?!is|will|as) in optional second-word block prevents
        # greedily capturing connective verbs (e.g. "Rahul is") as part of the name.
        exec_full_match = re.search(
            rf"(?:my\s+)?({_REL_ALT})\s+([A-Z][a-z]+(?:\s+(?!(?:is|will\b|as\b))[A-Z][a-z]+)?)\s+(?:is|will\s+be|as)?\s*(?:my\s+)?executor",
            msg,
            re.IGNORECASE,
        )
        # Case 2: "executor is [Name] and (he/she) is my [Rel]"
        exec_and_rel_match = re.search(
            r"(?:executor\s+is\s+)([A-Z][a-z]+)\s+and\s+(?:he|she|they)\s+is\s+(?:my\s+)?(\w+)",
            msg,
            re.IGNORECASE,
        )
        # Case 3: "change/appoint/executor is/to [Name]"
        exec_change_match = re.search(
            r"(?:change\s+(?:my\s+)?executor\s+to|appoint\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)|executor\s+(?:is|to))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            msg,
            re.IGNORECASE,
        )
        # Pronouns that should never be interpreted as an executor name
        _EXEC_NAME_PRONOUNS = {"he", "she", "they", "it", "i", "we", "you", "him", "her", "them"}

        # Case 4: "[Name] is my executor" — do NOT use IGNORECASE so [A-Z] requires uppercase
        # first letter (Title Case proper nouns), preventing 'is'/'he'/etc. from matching.
        exec_name_is_match = re.search(
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:is|will be)\s+(?:my\s+)?executor\b",
            msg,  # no re.IGNORECASE — intentional, ensures Title Case
        )
        # Case 5: "I want [Name]" when asked for executor
        exec_i_want_match = None
        if _asking_exec_name:
            exec_i_want_match = re.search(
                r"(?:i\s+want|i\s+choose|i\s+pick|i\s+select|appoint)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                msg,
                re.IGNORECASE,
            )
        # Case 6: Relationship follow-up — "He is my brother" / "Brother" / "my brother".
        # Checked BEFORE Case 7 so that pronoun-lead phrases route here (relationship only).
        exec_rel_followup = re.search(
            rf"^(?:he|she|they|[a-z]+)?\s*(?:is|'s)?\s*(?:my\s+)?({_REL_ALT})\b",
            msg,
            re.IGNORECASE,
        )
        # Case 7: "[Name] is my [rel]" (executor already known, just confirming rel).
        # Guarded: skip if the captured name is a pronoun or doesn't match the known executor.
        exec_name_is_rel_match = None
        if current_state.executor.name and not current_state.executor.relationship:
            _raw_match = re.search(
                rf"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+is\s+(?:my\s+)?({_REL_ALT})\b",
                msg,
                re.IGNORECASE,
            )
            if _raw_match:
                _candidate_name = _raw_match.group(1).strip()
                # Only accept if the candidate is NOT a pronoun
                if _candidate_name.lower() not in _EXEC_NAME_PRONOUNS:
                    exec_name_is_rel_match = _raw_match

        if exec_full_match:
            rel = exec_full_match.group(1).strip().capitalize()
            name = exec_full_match.group(2).strip()
            extracted.executor = Executor(name=name, relationship=rel)
            extracted_labels.append(f"executor ({name}, {rel})")
        elif exec_and_rel_match:
            name = exec_and_rel_match.group(1).strip()
            rel = exec_and_rel_match.group(2).strip().capitalize()
            extracted.executor = Executor(name=name, relationship=rel)
            extracted_labels.append(f"executor ({name}, {rel})")
        elif exec_change_match:
            name = (exec_change_match.group(1) or exec_change_match.group(2)).strip()
            extracted.executor = Executor(name=name, relationship=None)
            extracted_labels.append(f"executor name ({name})")
        elif exec_name_is_match:
            name = exec_name_is_match.group(1).strip()
            extracted.executor = Executor(name=name, relationship=None)
            extracted_labels.append(f"executor name ({name})")
        elif exec_i_want_match:
            name = exec_i_want_match.group(1).strip()
            extracted.executor = Executor(name=name, relationship=None)
            extracted_labels.append(f"executor name ({name})")
        elif exec_name_is_rel_match:
            name = exec_name_is_rel_match.group(1).strip()
            rel = exec_name_is_rel_match.group(2).strip().capitalize()
            extracted.executor = Executor(name=name, relationship=rel)
            extracted_labels.append(f"executor ({name}, {rel})")
        elif exec_rel_followup:
            rel = exec_rel_followup.group(1).strip().capitalize()
            extracted.executor = Executor(name=None, relationship=rel)
            extracted_labels.append(f"executor relationship ({rel})")
        elif _asking_exec_name:
            # Context-aware concise name: "Rahul" / "Rahul Sharma" when asked for executor
            _non_exec = {
                "yes", "no", "ok", "okay", "sure", "hello", "hi", "hey",
                "help", "skip", "none", "nothing", "idk", "please",
                "thanks", "thank you", "actually",
            } | set(_RELATIONSHIPS)
            cleaned_exec = msg.strip().rstrip(".").strip()
            exec_words = cleaned_exec.split()
            if 1 <= len(exec_words) <= 3:
                if not any(w.lower() in _non_exec for w in exec_words):
                    if all(re.match(r"^[A-Za-z]+(?:['\-][A-Za-z]+)?$", w) for w in exec_words):
                        extracted.executor = Executor(name=" ".join(w.capitalize() for w in exec_words), relationship=None)
                        extracted_labels.append(f"executor name ({extracted.executor.name})")
        elif _asking_exec_rel:
            # Context-aware: bare relationship word when asked
            rel_match = re.search(rf"^(?:my\s+)?({_REL_ALT})\s*\.?$", msg_lower)
            if rel_match:
                rel = rel_match.group(1).strip().capitalize()
                extracted.executor = Executor(name=None, relationship=rel)
                extracted_labels.append(f"executor relationship ({rel})")

        # ------------------------------------------------------------------
        # F. Specific Gifts & Additional Wishes (Optional Dimensions)
        # ------------------------------------------------------------------
        _asking_gifts = self._asking(
            last_asst,
            r"\b(specific gift|leave anything|bequeath|gift|wishes to include)\b",
        )
        _asking_wishes = self._asking(
            last_asst,
            r"\b(additional wish|any other wish|additional instruction|anything else|wishes to include)\b",
        )
        _asking_optional = _asking_gifts or _asking_wishes or bool(
            re.search(r"\b(specific gifts|additional wishes)\b", last_asst, re.IGNORECASE)
        )

        # Check for clear negative responses to optional questions
        _plain_no_optional = bool(
            re.search(
                r"^(?:"
                r"no|none|nothing|nothing\s+else|nothing\s+specific|none\s+at\s+all|"
                r"no\s+(?:specific\s+)?gifts?|no\s+additional\s+wishes?|no\s+wishes?|"
                r"no\s+other\s+wishes?|no\s+more\s+wishes?|"
                r"i\s+(?:do\s+not|don'?t)\s+have\s+(?:any|either)(?:\s+(?:specific\s+gifts?|additional\s+wishes?|gifts?|wishes?))?|"
                r"i\s+have\s+(?:none|nothing|no\s+(?:specific\s+)?gifts?|no\s+(?:additional\s+)?wishes?)|"
                r"no\s+thanks?|no\s+thank\s+you|nope|nah|"
                r"no,\s*(?:none|nothing|nothing\s+else|no\s+gifts?|no\s+wishes?|i\s+don'?t\s+have\s+any)"
                r")[\s.!]*$",
                msg_lower,
            )
        )

        if not _plain_no_optional:
            gift_match = re.search(
                r"(?:give|leave|gift|pass)\s+(?:my\s+)?([^.,;]+?)\s+to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                msg,
                re.IGNORECASE,
            )
            gift_match_alt = re.search(
                r"(?:my\s+(?:daughter|son|child|friend)\s+)?([A-Z][a-z]+)\s+should\s+receive\s+(?:my\s+)?([^.,;]+)",
                msg,
                re.IGNORECASE,
            )
            gift_gets_match = re.search(
                r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+gets?\s+(?:my\s+)?([^.,;]+)",
                msg,
                re.IGNORECASE,
            )
            gift_currency_match = re.search(
                r"(?:my\s+(?:" + _REL_ALT + r"))\s+gets?\s+(.+)",
                msg,
                re.IGNORECASE,
            )

            if gift_match:
                item = gift_match.group(1).strip()
                recipient = gift_match.group(2).strip()
                extracted.specific_gifts = [SpecificGift(recipient=recipient, item_or_amount=item)]
                extracted_labels.append(f"gift ({item} -> {recipient})")
            elif gift_match_alt:
                recipient = gift_match_alt.group(1).strip()
                item = gift_match_alt.group(2).strip()
                extracted.specific_gifts = [SpecificGift(recipient=recipient, item_or_amount=item)]
                extracted_labels.append(f"gift ({item} -> {recipient})")
            elif gift_gets_match:
                recipient = gift_gets_match.group(1).strip()
                item = gift_gets_match.group(2).strip()
                if item and recipient:
                    extracted.specific_gifts = [SpecificGift(recipient=recipient, item_or_amount=item)]
                    extracted_labels.append(f"gift ({item} -> {recipient})")

            wishes_match = re.search(
                r"(?:additional\s+wish(?:es)?|wish(?:es)?\s+are|i\s+wish\s+to|scatter\s+my\s+ashes|please\s+donate)\s*:?\s*(.+)",
                msg,
                re.IGNORECASE,
            )
            if wishes_match:
                extracted.additional_wishes = wishes_match.group(1).strip()
                extracted_labels.append("additional wishes")
            elif _asking_wishes and not extracted.specific_gifts:
                cleaned_wish = msg.strip().rstrip(".").strip()
                wish_stop = {
                    "yes", "ok", "okay", "sure", "hello", "hi", "hey", "thanks", "thank you",
                    "happy birthday", "good morning", "good evening", "how are you",
                }
                if (
                    cleaned_wish
                    and cleaned_wish.lower() not in wish_stop
                    and len(cleaned_wish) > 3
                    and re.search(r"\b(donate|bury|scatter|cremate|care\s+for|funeral|charity|organ|wishes|instruction|ensure|distribute|pet)\b", cleaned_wish, re.IGNORECASE)
                ):
                    extracted.additional_wishes = cleaned_wish
                    extracted_labels.append("additional wishes")

        # ------------------------------------------------------------------
        # Build intent and reply
        # ------------------------------------------------------------------
        intent = IntentType.CORRECTION if is_correction else IntentType.INFORM

        assistant_reply = self._generate_assistant_reply(
            extracted=extracted,
            extracted_labels=extracted_labels,
            current_state=current_state,
            is_correction=is_correction,
            is_negative_optional=_plain_no_optional,
            asking_optional=_asking_optional,
        )

        return LLMResponse(
            intent=intent,
            extracted_fields=extracted,
            assistant_reply=assistant_reply,
        )

    # ------------------------------------------------------------------
    # Reply generation
    # ------------------------------------------------------------------

    def _generate_assistant_reply(
        self,
        extracted: ExtractedFields,
        extracted_labels: List[str],
        current_state: IntakeState,
        is_correction: bool,
        is_negative_optional: bool = False,
        asking_optional: bool = False,
    ) -> str:
        """
        Formulates a natural assistant confirmation of extracted fields and asks the next missing question.
        """
        ack = ""
        if is_correction:
            ack = "I have noted that update. "
        elif extracted_labels:
            ack = f"Thank you. I have recorded your {', '.join(extracted_labels)}. "

        # Compute next required question based on state + candidate updates
        merged_name = extracted.full_name or current_state.full_name
        merged_addr = extracted.home_address or current_state.home_address
        merged_worldwide = (
            extracted.covers_worldwide_assets
            if extracted.covers_worldwide_assets is not None
            else current_state.covers_worldwide_assets
        )
        merged_has_children = (
            extracted.has_children
            if extracted.has_children is not None
            else current_state.has_children
        )
        merged_children = extracted.children if extracted.children is not None else current_state.children

        exec_name = (
            extracted.executor.name if extracted.executor and extracted.executor.name
            else current_state.executor.name
        )
        exec_rel = (
            extracted.executor.relationship if extracted.executor and extracted.executor.relationship
            else current_state.executor.relationship
        )

        # Prioritize relationship follow-up if an executor was just introduced without a relationship
        if exec_name and not exec_rel:
            next_q = f"What is {exec_name}'s relationship to you (e.g., brother, spouse, friend)?"
        elif not merged_name:
            next_q = "May I please have your full legal name?"
        elif not merged_addr:
            next_q = f"Nice to meet you, {merged_name}. What is your current residential home address?"
        elif merged_worldwide is None:
            next_q = "Does this Personal Wishes Document cover your assets worldwide, or only in your home country?"
        elif merged_has_children is None:
            next_q = "Do you have any children?"
        elif merged_has_children is True and not merged_children:
            next_q = "Could you please tell me the full names of your children?"
        elif not exec_name:
            next_q = "Who would you like to appoint as the executor of your wishes?"
        else:
            # All essential fields are satisfied
            if is_negative_optional:
                return "Thank you. Your Personal Wishes Document intake is now complete! All required information has been gathered and your draft document is ready for review."

            if current_state.is_complete:
                if extracted_labels:
                    return f"{ack}Your Personal Wishes Document intake is complete! All details have been recorded and your draft document is ready for review."
                return "Thank you. Your Personal Wishes Document intake is complete! All required information has been gathered and your draft document is ready for review."

            # First turn where all essential fields have just become satisfied
            next_q = (
                "We have captured all essential details for your draft document. "
                "Do you have any specific gifts you would like to assign, or any additional wishes to include?"
            )

        return f"{ack}{next_q}".strip()
