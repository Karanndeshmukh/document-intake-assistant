"""
Comprehensive End-to-End Scenario Tests for Document Intake Assistant.

Tests all 15 real-world multi-turn conversational journeys, error recovery,
edge cases, and full API-level workflows.
"""

import pytest
from fastapi.testclient import TestClient

from backend.conversation import ConversationOrchestrator
from backend.document_generator import DocumentGenerator
from backend.llm.base import LLMServiceError
from backend.llm.mock_llm import MockLLMService, MockMode
from backend.main import create_app
from backend.schemas import IntakeState
from backend.state_manager import SessionManager


class TestEndToEndScenarios:
    @pytest.fixture
    def setup_system(self):
        sm = SessionManager()
        llm = MockLLMService()
        orch = ConversationOrchestrator(session_manager=sm, llm_service=llm)
        app = create_app(session_manager=sm, orchestrator=orch)
        client = TestClient(app)
        return sm, llm, orch, client

    # --------------------------------------------------------------------------
    # SCENARIO 1: COMPLETE INTERVIEW FLOW
    # --------------------------------------------------------------------------
    def test_scenario_1_complete_interview(self, setup_system):
        """
        Simulate a full sequential interview capturing all 8 intake dimensions.
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Turn 1: Name
        r1 = client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        assert r1.status_code == 200

        # Turn 2: Address
        r2 = client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur, Maharashtra"})
        assert r2.status_code == 200

        # Turn 3: Worldwide assets
        r3 = client.post("/api/chat", json={"session_id": sid, "message": "Yes, cover worldwide assets"})
        assert r3.status_code == 200

        # Turn 4: Children
        r4 = client.post("/api/chat", json={"session_id": sid, "message": "I have children: Ananya and Rohan"})
        assert r4.status_code == 200

        # Turn 5: Executor Name & Relationship
        r5 = client.post("/api/chat", json={"session_id": sid, "message": "My brother Rahul is my executor"})
        assert r5.status_code == 200

        # Turn 6: Specific Gifts
        r6 = client.post("/api/chat", json={"session_id": sid, "message": "Give my vintage gold watch to Ananya"})
        assert r6.status_code == 200

        # Turn 7: Additional Wishes
        r7 = client.post("/api/chat", json={"session_id": sid, "message": "Additional wish: Donate books to city library"})
        assert r7.status_code == 200

        final_data = r7.json()
        final_state = final_data["state"]
        final_doc = final_data["draft_document"]

        # 1. State verification
        assert final_state["full_name"] == "Karan Deshmukh"
        assert final_state["home_address"] == "Nagpur, Maharashtra"
        assert final_state["covers_worldwide_assets"] is True
        assert final_state["has_children"] is True
        assert final_state["children"] == ["Ananya", "Rohan"]
        assert final_state["executor"]["name"] == "Rahul"
        assert final_state["executor"]["relationship"] == "Brother"
        assert len(final_state["specific_gifts"]) == 1
        assert final_state["specific_gifts"][0]["recipient"] == "Ananya"
        assert "vintage gold watch" in final_state["specific_gifts"][0]["item_or_amount"]
        assert "Donate books" in final_state["additional_wishes"]

        # 2. Completeness & Missing Fields
        assert final_data["missing_fields"] == []
        assert final_data["status"] == "complete"

        # 3. Document disclaimers & content
        assert "FICTIONAL DOCUMENT" in final_doc
        assert "NOT LEGAL ADVICE" in final_doc
        assert "Karan Deshmukh" in final_doc
        assert "Nagpur, Maharashtra" in final_doc
        assert "Yes (Covers assets worldwide" in final_doc
        assert "Ananya, Rohan" in final_doc
        assert "Rahul" in final_doc
        assert "Brother" in final_doc
        assert "To Ananya: vintage gold watch" in final_doc

    # --------------------------------------------------------------------------
    # SCENARIO 2: MULTI-FIELD ATOMIC INPUT
    # --------------------------------------------------------------------------
    def test_scenario_2_multi_field_input(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        user_msg = (
            "My name is Karan Deshmukh, I live in Nagpur, I don't have children, "
            "and my brother Rahul is my executor."
        )
        res = client.post("/api/chat", json={"session_id": sid, "message": user_msg})
        assert res.status_code == 200
        data = res.json()
        state = data["state"]

        assert state["full_name"] == "Karan Deshmukh"
        assert state["home_address"] == "Nagpur"
        assert state["has_children"] is False
        assert state["children"] == []
        assert state["executor"]["name"] == "Rahul"
        assert state["executor"]["relationship"] == "Brother"
        # Worldwide assets was not specified and must remain strictly null
        assert state["covers_worldwide_assets"] is None
        assert "covers_worldwide_assets" in data["missing_fields"]
        assert "worldwide" in data["assistant_message"].lower()

    # --------------------------------------------------------------------------
    # SCENARIO 3: PARTIAL EXECUTOR AUGMENTATION
    # --------------------------------------------------------------------------
    def test_scenario_3_partial_executor(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Turn 1: Name only
        r1 = client.post("/api/chat", json={"session_id": sid, "message": "Rahul is my executor."})
        assert r1.json()["state"]["executor"]["name"] == "Rahul"
        assert r1.json()["state"]["executor"]["relationship"] is None
        assert "relationship" in r1.json()["assistant_message"].lower()

        # Turn 2: Relationship only
        r2 = client.post("/api/chat", json={"session_id": sid, "message": "He is my brother"})
        state = r2.json()["state"]
        assert state["executor"]["name"] == "Rahul"
        assert state["executor"]["relationship"] == "Brother"

        doc = r2.json()["draft_document"]
        assert "Executor Name: Rahul" in doc
        assert "Relationship to Declarant: Brother" in doc

    # --------------------------------------------------------------------------
    # SCENARIO 4: EXPLICIT CORRECTION
    # --------------------------------------------------------------------------
    def test_scenario_4_explicit_correction(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Setup initial executor
        client.post("/api/chat", json={"session_id": sid, "message": "My brother Rahul is my executor"})
        assert client.get(f"/api/session/{sid}/state").json()["state"]["executor"]["name"] == "Rahul"

        # Explicit correction
        res = client.post("/api/chat", json={"session_id": sid, "message": "Actually, change my executor to Amit."})
        assert res.status_code == 200
        state = res.json()["state"]

        assert state["executor"]["name"] == "Amit"
        assert state["executor"]["relationship"] == "Brother"  # Relationship preserved
        assert "Executor Name: Amit" in res.json()["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 5: AMBIGUITY PRESERVES STATE & DOCUMENT
    # --------------------------------------------------------------------------
    def test_scenario_5_ambiguity(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        state_before = client.get(f"/api/session/{sid}/state").json()["state"]
        doc_before = client.get(f"/api/session/{sid}/document").json()["document"]

        # Ambiguous statement
        res = client.post("/api/chat", json={"session_id": sid, "message": "I want everything covered."})
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "clarification_needed"
        assert data["state"] == state_before  # State completely preserved
        assert data["draft_document"] == doc_before  # Document completely preserved
        assert data["pending_clarification"] is not None
        assert "worldwide" in data["assistant_message"].lower()

    # --------------------------------------------------------------------------
    # SCENARIO 6: CONTRADICTION BLOCKS MUTATION
    # --------------------------------------------------------------------------
    def test_scenario_6_contradiction(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Establish no children
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan and I don't have children."})
        state_before = client.get(f"/api/session/{sid}/state").json()["state"]
        doc_before = client.get(f"/api/session/{sid}/document").json()["document"]

        # Attempt contradictory statement without explicit correction
        res = client.post("/api/chat", json={"session_id": sid, "message": "My daughter Ananya should receive my car."})
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "contradiction_detected"
        assert data["state"] == state_before  # has_children remains False, children remains []
        assert data["draft_document"] == doc_before  # Document unaltered
        assert data["pending_clarification"] is not None
        assert data["pending_clarification"]["field_name"] == "has_children"

    # --------------------------------------------------------------------------
    # SCENARIO 7: CONTRADICTION RESOLUTION VIA CORRECTION
    # --------------------------------------------------------------------------
    def test_scenario_7_contradiction_resolution(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # 1. Establish has_children = False
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan and I have no children."})

        # 2. Contradiction occurs
        res_contra = client.post("/api/chat", json={"session_id": sid, "message": "My daughter Ananya should receive my car."})
        assert res_contra.json()["status"] == "contradiction_detected"

        # 3. User provides explicit correction resolving the conflict
        res_resolve = client.post(
            "/api/chat",
            json={"session_id": sid, "message": "Actually, mistake, I have a daughter Ananya"},
        )
        assert res_resolve.status_code == 200
        resolved_data = res_resolve.json()

        assert resolved_data["status"] == "in_progress"
        assert resolved_data["state"]["has_children"] is True
        assert resolved_data["state"]["children"] == ["Ananya"]
        assert resolved_data["pending_clarification"] is None
        assert "Ananya" in resolved_data["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 8: OFF-TOPIC MESSAGE
    # --------------------------------------------------------------------------
    def test_scenario_8_off_topic_message(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        state_before = client.get(f"/api/session/{sid}/state").json()["state"]

        res = client.post("/api/chat", json={"session_id": sid, "message": "What is the recipe for pasta?"})
        assert res.status_code == 200
        assert res.json()["state"] == state_before
        assert "Personal Wishes Document" in res.json()["assistant_message"]

    # --------------------------------------------------------------------------
    # SCENARIO 9: UNKNOWN INFORMATION REMAINS UNKNOWN
    # --------------------------------------------------------------------------
    def test_scenario_9_unknown_information_remains_null(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        state = client.get(f"/api/session/{sid}/state").json()["state"]

        assert state["home_address"] is None
        assert state["covers_worldwide_assets"] is None
        assert state["has_children"] is None
        assert state["children"] == []
        assert state["executor"]["name"] is None
        assert state["executor"]["relationship"] is None
        assert state["specific_gifts"] == []
        assert state["additional_wishes"] is None

    # --------------------------------------------------------------------------
    # SCENARIO 10: MULTI-SESSION ISOLATION
    # --------------------------------------------------------------------------
    def test_scenario_10_session_isolation(self, setup_system):
        sm, llm, orch, client = setup_system
        s1 = client.post("/api/session").json()["session_id"]
        s2 = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": s1, "message": "My name is Alice Johnson and I live in New York"})
        client.post("/api/chat", json={"session_id": s2, "message": "My name is Bob Smith and I live in London"})

        s1_state = client.get(f"/api/session/{s1}/state").json()["state"]
        s2_state = client.get(f"/api/session/{s2}/state").json()["state"]

        assert s1_state["full_name"] == "Alice Johnson"
        assert s1_state["home_address"] == "New York"
        assert s2_state["full_name"] == "Bob Smith"
        assert s2_state["home_address"] == "London"

        # Resetting s1 must not affect s2
        client.post(f"/api/session/{s1}/reset")
        assert client.get(f"/api/session/{s1}/state").json()["state"]["full_name"] is None
        assert client.get(f"/api/session/{s2}/state").json()["state"]["full_name"] == "Bob Smith"

    # --------------------------------------------------------------------------
    # SCENARIO 11: FAILURE RECOVERY SURVIVES PREVIOUS STATE
    # --------------------------------------------------------------------------
    def test_scenario_11_failure_recovery(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Valid turn
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        state_before = client.get(f"/api/session/{sid}/state").json()["state"]

        # Inject error
        llm.set_mode(MockMode.MALFORMED_JSON)
        res_fail = client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur"})
        assert res_fail.status_code == 500
        assert res_fail.json()["state"] == state_before  # State preserved

        # Restore normal operation
        llm.set_mode(MockMode.NORMAL)
        res_ok = client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur"})
        assert res_ok.status_code == 200
        assert res_ok.json()["state"]["home_address"] == "Nagpur"

    # --------------------------------------------------------------------------
    # SCENARIO 12: MALFORMED LLM RESPONSE
    # --------------------------------------------------------------------------
    def test_scenario_12_malformed_llm_response(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        state_before = client.get(f"/api/session/{sid}/state").json()["state"]
        doc_before = client.get(f"/api/session/{sid}/document").json()["document"]

        llm.set_mode(MockMode.INVALID_SCHEMA)
        res = client.post("/api/chat", json={"session_id": sid, "message": "Hello"})
        assert res.status_code == 500
        data = res.json()
        assert data["state"] == state_before
        assert data["draft_document"] == doc_before

    # --------------------------------------------------------------------------
    # SCENARIO 13: DOCUMENT DETERMINISM
    # --------------------------------------------------------------------------
    def test_scenario_13_document_determinism(self):
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            covers_worldwide_assets=True,
            has_children=True,
            children=["Ananya"],
        )
        runs = [DocumentGenerator.generate(state) for _ in range(5)]
        assert all(run == runs[0] for run in runs)

    # --------------------------------------------------------------------------
    # SCENARIO 14: SESSION RESET
    # --------------------------------------------------------------------------
    def test_scenario_14_session_reset(self, setup_system):
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Populate session
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan, I live in Nagpur."})
        assert client.get(f"/api/session/{sid}/state").json()["state"]["full_name"] == "Karan"

        # Reset
        res_reset = client.post(f"/api/session/{sid}/reset")
        assert res_reset.status_code == 200
        reset_state = res_reset.json()["state"]

        assert reset_state["full_name"] is None
        assert reset_state["home_address"] is None
        assert reset_state["children"] == []
        assert "Full Legal Name: [Not yet provided]" in res_reset.json()["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 15: COMPLETE REST API LIFECYCLE
    # --------------------------------------------------------------------------
    def test_scenario_15_api_level_complete_flow(self, setup_system):
        sm, llm, orch, client = setup_system

        # 1. Initialize
        s_res = client.post("/api/session")
        assert s_res.status_code == 201
        sid = s_res.json()["session_id"]

        # 2. Chat Turn 1
        c1 = client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        assert c1.status_code == 200
        assert c1.json()["state"]["full_name"] == "Karan Deshmukh"

        # 3. Chat Turn 2
        c2 = client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur, Maharashtra"})
        assert c2.status_code == 200
        assert c2.json()["state"]["home_address"] == "Nagpur, Maharashtra"

        # 4. Query GET /state
        st_res = client.get(f"/api/session/{sid}/state")
        assert st_res.status_code == 200
        assert st_res.json()["state"]["full_name"] == "Karan Deshmukh"

        # 5. Query GET /document
        doc_res = client.get(f"/api/session/{sid}/document")
        assert doc_res.status_code == 200
        assert "Karan Deshmukh" in doc_res.json()["document"]

        # 6. Reset
        rst_res = client.post(f"/api/session/{sid}/reset")
        assert rst_res.status_code == 200
        assert rst_res.json()["state"]["full_name"] is None

    # --------------------------------------------------------------------------
    # SCENARIO 16: WORLDWIDE ASSETS NEGATIVE PHRASING REGRESSION
    # --------------------------------------------------------------------------
    @pytest.mark.parametrize(
        "answer",
        [
            "only in my home country",
            "home country only",
            "not worldwide",
        ],
    )
    def test_scenario_16_worldwide_assets_negative_e2e(self, setup_system, answer):
        """
        Regression test: Answering negative phrasing for worldwide assets must:
        - Map covers_worldwide_assets to False (not None)
        - Remove covers_worldwide_assets from missing_fields
        - Advance the conversation without repeating the worldwide-assets question
        - Render 'No (Restricted to assets within primary home jurisdiction)' in the draft document
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Turn 1: Name
        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})

        # Turn 2: Address -> leads to worldwide assets question
        r2 = client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur, Maharashtra"})
        assert "worldwide" in r2.json()["assistant_message"].lower()

        # Turn 3: User answers with negative phrasing
        r3 = client.post("/api/chat", json={"session_id": sid, "message": answer})
        assert r3.status_code == 200
        data = r3.json()

        # 1. covers_worldwide_assets is False and no longer None
        assert data["state"]["covers_worldwide_assets"] is False

        # 2. missing_fields is updated correctly
        assert "covers_worldwide_assets" not in data["missing_fields"]

        # 3. Assistant does not repeat the worldwide-assets question, advances to children
        assert "worldwide, or only in your home country" not in data["assistant_message"].lower()
        assert "children" in data["assistant_message"].lower()

        # 4. Draft document shows the confirmed answer
        assert "No (Restricted to assets within primary home jurisdiction)" in data["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 17: WORLDWIDE ASSETS POSITIVE PHRASING REGRESSION
    # --------------------------------------------------------------------------
    @pytest.mark.parametrize(
        "answer",
        [
            "yes, worldwide",
            "globally",
        ],
    )
    def test_scenario_17_worldwide_assets_positive_e2e(self, setup_system, answer):
        """
        Regression test: Answering positive phrasing for worldwide assets must:
        - Map covers_worldwide_assets to True (not None)
        - Remove covers_worldwide_assets from missing_fields
        - Advance the conversation to the children question
        - Render 'Yes (Covers assets worldwide across all jurisdictions)' in the draft document
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        client.post("/api/chat", json={"session_id": sid, "message": "My name is Karan Deshmukh"})
        client.post("/api/chat", json={"session_id": sid, "message": "I live in Nagpur, Maharashtra"})

        r3 = client.post("/api/chat", json={"session_id": sid, "message": answer})
        assert r3.status_code == 200
        data = r3.json()

        assert data["state"]["covers_worldwide_assets"] is True
        assert "covers_worldwide_assets" not in data["missing_fields"]
        assert "worldwide, or only in your home country" not in data["assistant_message"].lower()
        assert "children" in data["assistant_message"].lower()
        assert "Yes (Covers assets worldwide across all jurisdictions)" in data["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 18: CONCISE NAME AT SESSION START (E2E REGRESSION)
    # --------------------------------------------------------------------------
    def test_scenario_18_concise_name_at_session_start(self, setup_system):
        """
        Regression test: When the assistant's opening message asks for the full legal name
        and the user replies with only their name (e.g. 'Karan Deshmukh'), the system must:
        - Store state.full_name == 'Karan Deshmukh'  (not None)
        - Remove 'full_name' from missing_fields
        - Advance the conversation to the next required field (home address)
        """
        sm, llm, orch, client = setup_system

        # POST /api/session - server issues greeting asking for full legal name
        s_res = client.post("/api/session")
        assert s_res.status_code == 201
        sid = s_res.json()["session_id"]
        initial_message = s_res.json()["initial_message"]
        assert "name" in initial_message.lower()

        # POST /api/chat - user replies with just their name
        r1 = client.post("/api/chat", json={"session_id": sid, "message": "Karan Deshmukh"})
        assert r1.status_code == 200
        data = r1.json()

        # full_name must be captured
        assert data["state"]["full_name"] == "Karan Deshmukh"
        # full_name must be removed from missing_fields
        assert "full_name" not in data["missing_fields"]
        # assistant must advance to the next question (home address)
        assert "address" in data["assistant_message"].lower()
        # draft document must reflect the name
        assert "Karan Deshmukh" in data["draft_document"]

    def test_scenario_18b_alice_johnson_concise_name(self, setup_system):
        """
        Regression test: Different name 'Alice Johnson' at session start is stored correctly.
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        r1 = client.post("/api/chat", json={"session_id": sid, "message": "Alice Johnson"})
        assert r1.status_code == 200
        data = r1.json()

        assert data["state"]["full_name"] == "Alice Johnson"
        assert "full_name" not in data["missing_fields"]
        assert "address" in data["assistant_message"].lower()

    # --------------------------------------------------------------------------
    # SCENARIO 19: CONCISE ADDRESS EXTRACTION E2E REGRESSION
    # --------------------------------------------------------------------------
    @pytest.mark.parametrize(
        "address_reply",
        [
            "Nagpur India",
            "Nagpur",
            "123 MG Road, Nagpur",
            "Pune, Maharashtra",
        ],
    )
    def test_scenario_19_concise_address_e2e(self, setup_system, address_reply):
        """
        Regression test: When the assistant asks for a home address and the user
        replies concisely (without 'I live in …'), the system must:
        - Store state.home_address == the replied text
        - Remove 'home_address' from missing_fields
        - Advance the conversation to the worldwide-assets question
        - Not repeat the address question
        """
        sm, llm, orch, client = setup_system

        sid = client.post("/api/session").json()["session_id"]

        # Turn 1: supply name concisely so assistant advances to address question
        r1 = client.post("/api/chat", json={"session_id": sid, "message": "Karan Deshmukh"})
        assert r1.status_code == 200
        assert r1.json()["state"]["full_name"] == "Karan Deshmukh"
        assert "address" in r1.json()["assistant_message"].lower()

        # Turn 2: supply address concisely
        r2 = client.post("/api/chat", json={"session_id": sid, "message": address_reply})
        assert r2.status_code == 200
        data = r2.json()

        # home_address must be captured
        assert data["state"]["home_address"] == address_reply, (
            f"Expected home_address={address_reply!r}, got {data['state']['home_address']!r}"
        )
        # home_address must leave missing_fields
        assert "home_address" not in data["missing_fields"]
        # assistant must advance to worldwide-assets question, not repeat address
        assert "worldwide" in data["assistant_message"].lower()
        assert "address" not in data["assistant_message"].lower() or "worldwide" in data["assistant_message"].lower()
        # draft document must reflect the address
        assert address_reply in data["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 20: NEGATIVE OPTIONAL RESPONSES E2E
    # --------------------------------------------------------------------------
    @pytest.mark.parametrize(
        "neg_response",
        [
            "no",
            "none",
            "nothing",
            "nothing else",
            "no specific gifts",
            "no additional wishes",
            "I don't have any",
            "I have none",
        ],
    )
    def test_scenario_20_negative_optional_gifts_and_wishes_e2e(self, setup_system, neg_response):
        """
        Scenario 20: Full interview where all 6 essential fields are filled,
        assistant asks the optional gifts/wishes question, and user replies with
        a negative response.
        Verifies:
        - specific_gifts remains empty []
        - additional_wishes remains None
        - Assistant does not repeat the question and produces a completion response
        - Session status is 'complete' and missing_fields is empty
        - Draft document remains valid and contains all confirmed essential fields
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # 1. Name
        client.post("/api/chat", json={"session_id": sid, "message": "Karan Deshmukh"})
        # 2. Address
        client.post("/api/chat", json={"session_id": sid, "message": "Nagpur, India"})
        # 3. Worldwide Assets
        client.post("/api/chat", json={"session_id": sid, "message": "worldwide"})
        # 4. Children
        client.post("/api/chat", json={"session_id": sid, "message": "No children"})
        # 5. Executor (Name + Relationship)
        r5 = client.post("/api/chat", json={"session_id": sid, "message": "My brother Rahul is my executor"})
        assert r5.status_code == 200
        assert "specific gifts" in r5.json()["assistant_message"].lower()

        # 6. Negative response to optional gifts/wishes question
        r6 = client.post("/api/chat", json={"session_id": sid, "message": neg_response})
        assert r6.status_code == 200
        data6 = r6.json()

        # State checks
        assert data6["state"]["specific_gifts"] == []
        assert data6["state"]["additional_wishes"] is None
        assert data6["state"]["full_name"] == "Karan Deshmukh"
        assert data6["state"]["executor"]["name"] == "Rahul"
        assert data6["state"]["executor"]["relationship"] == "Brother"

        # Session & completion checks
        assert data6["status"] == "complete"
        assert data6["missing_fields"] == []
        assert "complete" in data6["assistant_message"].lower()
        assert "specific gifts you would like to assign" not in data6["assistant_message"].lower()

        # Draft document checks
        assert "Karan Deshmukh" in data6["draft_document"]
        assert "Rahul" in data6["draft_document"]
        assert "None specified" in data6["draft_document"]

    # --------------------------------------------------------------------------
    # SCENARIO 21: UNRELATED INPUT DURING OPTIONAL TURN
    # --------------------------------------------------------------------------
    def test_scenario_21_unrelated_input_during_optional_turn(self, setup_system):
        """
        Scenario 21: Unrelated input such as 'happy birthday' during optional turn
        is not incorrectly stored as a gift or additional wish.
        """
        sm, llm, orch, client = setup_system
        sid = client.post("/api/session").json()["session_id"]

        # Setup complete essential fields
        client.post("/api/chat", json={"session_id": sid, "message": "Karan Deshmukh"})
        client.post("/api/chat", json={"session_id": sid, "message": "Nagpur, India"})
        client.post("/api/chat", json={"session_id": sid, "message": "worldwide"})
        client.post("/api/chat", json={"session_id": sid, "message": "No children"})
        client.post("/api/chat", json={"session_id": sid, "message": "My brother Rahul is my executor"})

        # Send unrelated message
        r_unrelated = client.post("/api/chat", json={"session_id": sid, "message": "happy birthday"})
        assert r_unrelated.status_code == 200
        data = r_unrelated.json()

        assert data["state"]["specific_gifts"] == []
        assert data["state"]["additional_wishes"] is None
        assert data["status"] == "complete"



