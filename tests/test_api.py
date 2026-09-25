"""
API integration tests for FastAPI backend endpoints.

Tests cover:
1. POST /api/session creates session with HTTP 201
2. Session response contains initial empty state
3. Session response contains initial draft document
4. POST /api/chat processes user turns
5. Multi-turn conversation works end-to-end via API
6. Multi-field extraction in single API call
7. GET /api/session/{session_id}/state endpoint
8. GET /api/session/{session_id}/document endpoint
9. POST /api/session/{session_id}/reset endpoint
10. Missing session returns 404 Not Found
11. Invalid request payload returns 422 Unprocessable Entity
12. Ambiguous input preserves state across API calls
13. Contradictory input preserves state and document across API calls
14. LLM failure returns appropriate 500 error without crashing
15. Malformed LLM response returns 500 error while preserving state
16. Multiple sessions remain completely isolated
17. CORS middleware is configured
"""

import pytest
from fastapi.testclient import TestClient

from backend.conversation import ConversationOrchestrator
from backend.llm.base import LLMServiceError
from backend.llm.mock_llm import MockLLMService, MockMode
from backend.main import create_app
from backend.state_manager import SessionManager


class TestFastAPIEndpoints:
    @pytest.fixture
    def client(self):
        sm = SessionManager()
        llm = MockLLMService()
        orch = ConversationOrchestrator(session_manager=sm, llm_service=llm)
        app = create_app(session_manager=sm, orchestrator=orch)
        return TestClient(app)

    def test_1_create_session(self, client):
        """Test 1: POST /api/session creates a new session with 201 Created."""
        response = client.post("/api/session")
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert data["session_id"] != ""

    def test_2_session_response_contains_initial_state(self, client):
        """Test 2: Initial session returns default IntakeState with null fields."""
        response = client.post("/api/session")
        data = response.json()
        state = data["state"]
        assert state["full_name"] is None
        assert state["home_address"] is None
        assert state["covers_worldwide_assets"] is None
        assert state["has_children"] is None
        assert state["children"] == []
        assert state["executor"]["name"] is None

    def test_3_session_response_contains_initial_document(self, client):
        """Test 3: Initial session returns standard draft document with disclaimer."""
        response = client.post("/api/session")
        data = response.json()
        doc = data["draft_document"]
        assert "FICTIONAL DOCUMENT" in doc
        assert "NOT LEGAL ADVICE" in doc
        assert "Full Legal Name: [Not yet provided]" in doc

    def test_4_post_chat_works(self, client):
        """Test 4: POST /api/chat returns updated state and assistant message."""
        # Create session
        init_res = client.post("/api/session").json()
        sid = init_res["session_id"]

        # Send chat message
        chat_res = client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        assert chat_res.status_code == 200
        data = chat_res.json()
        assert data["session_id"] == sid
        assert data["state"]["full_name"] == "Karan Deshmukh"
        assert "Full Legal Name: Karan Deshmukh" in data["draft_document"]
        assert data["status"] == "in_progress"

    def test_5_multi_turn_conversation_via_api(self, client):
        """Test 5: Multi-turn flow via API correctly accumulates state."""
        sid = client.post("/api/session").json()["session_id"]

        # Turn 1: Name
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        # Turn 2: Address
        client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur"})

        # Turn 3: Executor name
        client.post("/api/chat", json={"session_id": sid, "message": "Rahul is my executor."})

        # Turn 4: Executor relationship
        t4_res = client.post("/api/chat", json={"session_id": sid, "message": "He is my brother"})
        data = t4_res.json()

        assert data["state"]["full_name"] == "Karan Deshmukh"
        assert data["state"]["home_address"] == "Nagpur"
        assert data["state"]["executor"]["name"] == "Rahul"
        assert data["state"]["executor"]["relationship"] == "Brother"

    def test_6_multi_field_extraction(self, client):
        """Test 6: Single chat call extracts multiple fields."""
        sid = client.post("/api/session").json()["session_id"]
        user_msg = (
            "My name is Karan Deshmukh, I live in Nagpur, I don't have children, "
            "and my brother Rahul is my executor."
        )
        res = client.post("/api/chat", json={"session_id": sid, "message": user_msg})
        assert res.status_code == 200
        state = res.json()["state"]

        assert state["full_name"] == "Karan Deshmukh"
        assert state["home_address"] == "Nagpur"
        assert state["has_children"] is False
        assert state["executor"]["name"] == "Rahul"
        assert state["executor"]["relationship"] == "Brother"

    def test_7_get_state_endpoint(self, client):
        """Test 7: GET /api/session/{session_id}/state returns current state."""
        sid = client.post("/api/session").json()["session_id"]
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        state_res = client.get(f"/api/session/{sid}/state")
        assert state_res.status_code == 200
        data = state_res.json()
        assert data["session_id"] == sid
        assert data["state"]["full_name"] == "Karan Deshmukh"
        assert "home_address" in data["missing_fields"]
        assert not data["is_complete"]

    def test_8_get_document_endpoint(self, client):
        """Test 8: GET /api/session/{session_id}/document returns generated draft."""
        sid = client.post("/api/session").json()["session_id"]
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        doc_res = client.get(f"/api/session/{sid}/document")
        assert doc_res.status_code == 200
        data = doc_res.json()
        assert data["session_id"] == sid
        assert "Full Legal Name: Karan Deshmukh" in data["document"]
        assert "FICTIONAL DOCUMENT" in data["document"]

    def test_9_reset_endpoint(self, client):
        """Test 9: POST /api/session/{session_id}/reset resets state."""
        sid = client.post("/api/session").json()["session_id"]
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        reset_res = client.post(f"/api/session/{sid}/reset")
        assert reset_res.status_code == 200
        data = reset_res.json()
        assert data["state"]["full_name"] is None
        assert "Full Legal Name: [Not yet provided]" in data["draft_document"]

    def test_10_missing_session_returns_404(self, client):
        """Test 10: Requests to non-existent session ID return 404."""
        bad_id = "non-existent-session-id"
        assert client.get(f"/api/session/{bad_id}/state").status_code == 404
        assert client.get(f"/api/session/{bad_id}/document").status_code == 404
        assert client.post(f"/api/session/{bad_id}/reset").status_code == 404
        assert client.post("/api/chat", json={"session_id": bad_id, "message": "Hi"}).status_code == 404

    def test_11_invalid_request_returns_422(self, client):
        """Test 11: Blank or empty messages return 422 Unprocessable Entity."""
        sid = client.post("/api/session").json()["session_id"]

        # Empty whitespace string
        res = client.post("/api/chat", json={"session_id": sid, "message": "   "})
        assert res.status_code == 422

        # Missing required message field
        res_missing = client.post("/api/chat", json={"session_id": sid})
        assert res_missing.status_code == 422

    def test_12_ambiguous_input_preserves_state(self, client):
        """Test 12: Ambiguous message returns clarification status and preserves state."""
        sid = client.post("/api/session").json()["session_id"]
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        res = client.post("/api/chat", json={"session_id": sid, "message": "I want everything covered."})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "clarification_needed"
        assert data["state"]["full_name"] == "Karan Deshmukh"
        assert data["state"]["covers_worldwide_assets"] is None
        assert data["pending_clarification"] is not None

    def test_13_contradictory_input_preserves_state_and_document(self, client):
        """Test 13: Contradictory input flags conflict without altering state or document."""
        sid = client.post("/api/session").json()["session_id"]
        # Set has_children = False
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan, I don't have children."})

        # Claim daughter
        res = client.post("/api/chat", json={"session_id": sid, "message": "My daughter Ananya should receive my car."})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "contradiction_detected"
        assert data["state"]["has_children"] is False
        assert data["state"]["children"] == []
        assert "Status: Declared no children." in data["draft_document"]

    def test_14_llm_failure_returns_appropriate_error(self):
        """Test 14: LLMServiceError returns clean 500 error while preserving state."""
        sm = SessionManager()

        class ErrorLLM(MockLLMService):
            def generate_response(self, user_message, current_state, history=None):
                raise LLMServiceError("Service unavailable")

        orch = ConversationOrchestrator(sm, ErrorLLM())
        app = create_app(session_manager=sm, orchestrator=orch)
        client = TestClient(app)

        sid = client.post("/api/session").json()["session_id"]
        res = client.post("/api/chat", json={"session_id": sid, "message": "Hello"})
        assert res.status_code == 500
        data = res.json()
        assert data["status"] == "error"
        assert "technical difficulties" in data["assistant_message"].lower()

    def test_15_malformed_llm_response_returns_appropriate_error(self):
        """Test 15: Malformed JSON from LLM returns clean 500 without stack traces."""
        sm = SessionManager()
        mock_llm = MockLLMService(mode=MockMode.MALFORMED_JSON)
        orch = ConversationOrchestrator(sm, mock_llm)
        app = create_app(session_manager=sm, orchestrator=orch)
        client = TestClient(app)

        sid = client.post("/api/session").json()["session_id"]
        res = client.post("/api/chat", json={"session_id": sid, "message": "Hello"})
        assert res.status_code == 500
        data = res.json()
        assert data["status"] == "error"
        assert "trouble processing" in data["assistant_message"].lower()

    def test_16_multiple_sessions_remain_isolated(self, client):
        """Test 16: Two concurrent sessions in FastAPI remain fully partitioned."""
        s1 = client.post("/api/session").json()["session_id"]
        s2 = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": s1, "message": "My name is User One"})
        client.post("/api/chat", json={"session_id": s2, "message": "My name is User Two"})

        s1_data = client.get(f"/api/session/{s1}/state").json()
        s2_data = client.get(f"/api/session/{s2}/state").json()

        assert s1_data["state"]["full_name"] == "User One"
        assert s2_data["state"]["full_name"] == "User Two"

    def test_17_cors_middleware_configured(self, client):
        """Test 17: CORS preflight requests receive appropriate headers."""
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers
