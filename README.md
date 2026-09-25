# Document Intake Assistant

A state-driven conversational interview web application built with **FastAPI**, **Pydantic**, **Vanilla JavaScript**, and **Google Gemini / Mock LLM** to collect structured personal information and generate a draft **Personal Wishes Document**.

> **IMPORTANT NOTICE:**  
> 1. **FICTIONAL DOCUMENT** — This project is an engineering demonstration created for the WenUp technical evaluation.  
> 2. **NOT LEGAL ADVICE** — This application does not provide legal advice, nor does it create a legally binding last will or legal instrument.

---

## Features

- **Multi-Turn Conversational Interview**: Conducts an iterative, polite interview asking for missing information in order of priority.
- **Structured State as Source of Truth**: `IntakeState` is the single source of truth; conversation logs are strictly partitioned from the state model.
- **Multi-Field Atomic Extraction**: Extracts multiple dimensions (e.g. name, address, child status, executor) provided in a single user message.
- **Partial Information Handling**: Supports partial executor details (e.g. name provided first, relationship provided later) without inventing missing attributes.
- **Ambiguity & Clarification**: Statements like *"I want everything covered"* trigger targeted clarification questions rather than making unsafe assumptions.
- **Contradiction Detection & Resolution**: Conflicting statements (e.g., declaring no children, then naming a daughter) are blocked from mutating state until explicitly resolved by the user.
- **Explicit Corrections**: User corrections (e.g., *"Actually, change my executor to Amit"*) update the target field while preserving unaffected information.
- **Unknown Values Preserved**: Unknown values are preserved. Missing information remains explicitly `None` / `[Not yet provided]`. The LLM never directly mutates application state, and document generation uses only validated structured state.
- **Deterministic Document Generation**: Generates standard, idempotent draft documents from confirmed state without LLM hallucinations.
- **Dual LLM Architecture**: Seamlessly switch between `MockLLMService` (offline deterministic testing) and `GeminiLLMService` (Google Gemini JSON mode).
- **Responsive 3-Panel UI**: Real-time Chat Panel, Live Structured State Panel, and Live Draft Document Preview.
- **Dockerized**: Containerized deployment with environment-based configuration.

---

## Architecture

```
+-----------------------------------------------------------------------------------+
|                                  BROWSER CLIENT                                   |
|                  Vanilla HTML5 / CSS3 / ES6 JavaScript (3-Panel UI)               |
+-----------------------------------------+-----------------------------------------+
                                          | HTTP REST (JSON)
                                          v
+-----------------------------------------------------------------------------------+
|                                 FASTAPI API LAYER                                 |
|          POST /api/session  |  POST /api/chat  |  GET /api/session/.../state      |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           CONVERSATION ORCHESTRATOR                               |
|        Coordinates extraction, validation, session updates, and draft rendering    |
+-------------------+---------------------+--------------------+--------------------+
                    |                     |                    |
                    v                     v                    v
+-----------------------+ +-------------------------+ +-----------------------------+
|      LLM SERVICE      | |   VALIDATION ENGINE     | |      DOCUMENT ENGINE        |
| - LLMService Interface| | - Deterministic Rules   | | - Pure Template Engine      |
| - MockLLMService      | | - Contradiction Gate    | | - Idempotent Rendering      |
| - GeminiLLMService    | | - Ambiguity Detection   | | - Strict Disclaimers        |
+-----------------------+ +-------------------------+ +-----------------------------+
                    |                     |                    |
                    +---------------------+--------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                                  SESSION MANAGER                                  |
|         In-Memory Session Store: IntakeState + ChatHistory + Clarifications      |
+-----------------------------------------------------------------------------------+
```

### Component Responsibilities

| Component | File | Responsibility |
| :--- | :--- | :--- |
| **`SessionManager`** | [`backend/state_manager.py`](backend/state_manager.py) | Manages in-memory session lifecycles, chat history, and isolated `IntakeState` instances. |
| **`LLMService`** | [`backend/llm/base.py`](backend/llm/base.py) | Abstract interface defining extraction and response generation (`MockLLMService`, `GeminiLLMService`). |
| **`ValidationEngine`** | [`backend/validation.py`](backend/validation.py) | Deterministic guardrails: detects contradictions, blocks ambiguities, and executes explicit corrections. |
| **`ConversationOrchestrator`** | [`backend/conversation.py`](backend/conversation.py) | Transactional pipeline coordinator connecting Session, LLM, Validation, and Document generation. |
| **`DocumentGenerator`** | [`backend/document_generator.py`](backend/document_generator.py) | Formats confirmed state into a structured, readable Personal Wishes Document. |

---

## Structured State Model

```python
class IntakeState(BaseModel):
    full_name: Optional[str] = None
    home_address: Optional[str] = None
    covers_worldwide_assets: Optional[bool] = None
    has_children: Optional[bool] = None
    children: List[str] = []
    executor: Executor = Executor(name=None, relationship=None)
    specific_gifts: List[SpecificGift] = []
    additional_wishes: Optional[str] = None
```

### State Transaction Safety
The LLM never directly mutates `IntakeState`. Every candidate update passes through:
```text
old_state -> LLM candidate extraction -> ValidationEngine -> validated state update -> commit new state
```
If validation fails (e.g. ambiguity, contradiction, or malformed JSON), `old_state` remains unchanged.

---

## API Documentation

### 1. Create Session
`POST /api/session`
```json
// Response (201 Created)
{
  "session_id": "032d5c37-0401-482f-bff3-08de0e882fb2",
  "state": {
    "full_name": null,
    "home_address": null,
    "covers_worldwide_assets": null,
    "has_children": null,
    "children": [],
    "executor": { "name": null, "relationship": null },
    "specific_gifts": [],
    "additional_wishes": null
  },
  "initial_message": "Hello! I am your Document Intake Assistant...",
  "draft_document": "============================================================\n..."
}
```

### 2. Conversational Chat
`POST /api/chat`
```json
// Request Body
{
  "session_id": "032d5c37-0401-482f-bff3-08de0e882fb2",
  "message": "My name is Karan Deshmukh, I live in Nagpur, and my brother Rahul is my executor."
}

// Response (200 OK)
{
  "session_id": "032d5c37-0401-482f-bff3-08de0e882fb2",
  "assistant_message": "Thank you. I have recorded your name, address, executor (Rahul, Brother). Does this document cover assets worldwide, or only in your home country?",
  "state": {
    "full_name": "Karan Deshmukh",
    "home_address": "Nagpur",
    "covers_worldwide_assets": null,
    "has_children": null,
    "children": [],
    "executor": { "name": "Rahul", "relationship": "Brother" },
    "specific_gifts": [],
    "additional_wishes": null
  },
  "draft_document": "...",
  "missing_fields": ["covers_worldwide_assets", "has_children"],
  "status": "in_progress",
  "pending_clarification": null
}
```

### 3. Query State
`GET /api/session/{session_id}/state`

### 4. Query Document
`GET /api/session/{session_id}/document`

### 5. Reset Session
`POST /api/session/{session_id}/reset`

---

## Local Setup

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.11, 3.12, 3.14)
- Git

### 2. Clone & Virtual Environment Setup
```bash
# Clone the repository
git clone <repo-url>
cd document-intake-assistant

# Create virtual environment
py -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
```bash
# Copy example configuration
cp .env.example .env
```

By default, `.env` runs in mock mode:
```ini
LLM_PROVIDER=mock
HOST=127.0.0.1
PORT=8000
```

### 4. Run Development Server
```bash
py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser and navigate to:
```
http://127.0.0.1:8000
```

---

## Google Gemini LLM Setup

To use the Google Gemini model instead of the mock engine:

1. Obtain an API key from [Google AI Studio](https://aistudio.google.com/).
2. Update `.env`:
   ```ini
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```
3. Restart the FastAPI server.

> **Security Note:** The browser UI communicates strictly with the local FastAPI backend. `GEMINI_API_KEY` is never sent to the browser or logged in responses.

---

## Automated Testing

The complete test suite runs offline and does not require an external API key:

```bash
py -m pytest -v
```

### Test Suite Summary (167 passing tests):
- `tests/test_schemas.py` (14 tests) — Structured state validation, executor/children consistency, API schemas.
- `tests/test_state_manager.py` (7 tests) — In-memory session CRUD, isolation, clarification state.
- `tests/test_validation.py` (9 tests) — Business rules, contradiction detection, partial fields, corrections.
- `tests/test_mock_llm.py` (42 tests) — Deterministic extraction, multi-field, worldwide phrasing (12 parameterized cases), address/name extraction, optional gifts/wishes negative handling (10 parameterized cases), off-topic rejection, fault injection.
- `tests/test_conversation.py` (15 tests) — Orchestrator turn lifecycle, error boundaries, message logging.
- `tests/test_document_gen.py` (15 tests) — Document formatting, disclaimers, deterministic equality.
- `tests/test_api.py` (17 tests) — REST API endpoints, CORS headers, 404/422/500 handlers.
- `tests/test_e2e_scenarios.py` (35 tests) — Full multi-turn user journeys, worldwide phrasing regressions (5 parameterized cases), address parsing (4 parameterized cases), optional negative gifts/wishes handling (8 parameterized cases), contradiction resolution, failure recovery.
- `tests/test_gemini_llm.py` (13 tests) — Gemini JSON parsing, error handling, provider factory.

---

## Docker Deployment

### 1. Build the Docker Image
```bash
docker build -t document-intake-assistant .
```

### 2. Run in Mock Mode (Default)
```bash
docker run --rm -p 8000:8000 document-intake-assistant
```

### 3. Run with Gemini
```bash
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=gemini \
  -e GEMINI_API_KEY="your_actual_gemini_api_key" \
  -e GEMINI_MODEL="gemini-2.5-flash" \
  document-intake-assistant
```

Access the UI at `http://localhost:8000`.

---

## Current Limitations & Production Roadmap

1. **In-Memory Session Store**: Sessions are held in memory; restarting the server clears active sessions. In production, this should be backed by Redis or PostgreSQL.
2. **Single-Process Memory**: Designed for single-instance or sticky-session deployments.
3. **No Authentication**: Sessions use generated UUIDs without user authentication.
4. **Fictional Document Scope**: Designed specifically for the Personal Wishes Document intake exercise.

See [`PRODUCTION_NOTES.md`](PRODUCTION_NOTES.md) for full architectural recommendations on scaling, persistence, security, and observability.
