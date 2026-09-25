"""
Unit and integration tests for DocumentGenerator and draft document lifecycle.

Tests cover:
1. Empty/default state rendering
2. Full completed state rendering
3. Partial state rendering
4. Unknown worldwide-assets status
5. has_children=False ('No children')
6. has_children=True with child names
7. has_children=True without names
8. Partial executor rendering (name only / relationship only)
9. Specific gifts rendering
10. Additional wishes rendering
11. No hallucinated or invented information
12. Deterministic output (re-running produces identical strings)
13. Orchestrator returns updated document after confirmed update
14. Ambiguous input does not change document
15. Contradictory input does not change document
"""

import pytest

from backend.conversation import ConversationOrchestrator
from backend.document_generator import DocumentGenerator
from backend.llm.mock_llm import MockLLMService
from backend.schemas import (
    Executor,
    IntakeState,
    SpecificGift,
)
from backend.state_manager import SessionManager


class TestDocumentGenerator:
    def test_1_empty_default_state(self):
        """Test 1: Default empty state displays all disclaimers and '[Not yet provided]' tags."""
        state = IntakeState()
        doc = DocumentGenerator.generate(state)

        assert "FICTIONAL DOCUMENT" in doc
        assert "NOT LEGAL ADVICE" in doc
        assert "Full Legal Name: [Not yet provided]" in doc
        assert "Residential Address: [Not yet provided]" in doc
        assert "Covers Worldwide Assets: [Not yet provided]" in doc
        assert "Status: [Not yet provided]" in doc
        assert "Executor Name: [Not yet provided]" in doc
        assert "Relationship to Declarant: [Not yet provided]" in doc

    def test_2_full_completed_state(self):
        """Test 2: Complete state formats all sections accurately."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur, Maharashtra, India",
            covers_worldwide_assets=True,
            has_children=True,
            children=["Ananya", "Rohan"],
            executor=Executor(name="Rahul Deshmukh", relationship="Brother"),
            specific_gifts=[
                SpecificGift(recipient="Ananya", item_or_amount="Vintage gold watch"),
                SpecificGift(recipient="Rohan", item_or_amount="500,000 INR education fund"),
            ],
            additional_wishes="I wish for my personal library to be donated to the city reading room.",
        )
        doc = DocumentGenerator.generate(state)

        assert "Karan Deshmukh" in doc
        assert "Nagpur, Maharashtra, India" in doc
        assert "Yes (Covers assets worldwide across all jurisdictions)" in doc
        assert "Ananya, Rohan" in doc
        assert "Rahul Deshmukh" in doc
        assert "Brother" in doc
        assert "To Ananya: Vintage gold watch" in doc
        assert "To Rohan: 500,000 INR education fund" in doc
        assert "personal library to be donated" in doc

    def test_3_partial_state(self):
        """Test 3: Partial state shows known items and keeps unknowns marked clearly."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
        )
        doc = DocumentGenerator.generate(state)

        assert "Full Legal Name: Karan Deshmukh" in doc
        assert "Residential Address: Nagpur" in doc
        assert "Covers Worldwide Assets: [Not yet provided]" in doc
        assert "Executor Name: [Not yet provided]" in doc

    def test_4_unknown_worldwide_assets_status(self):
        """Test 4: Worldwide assets remains '[Not yet provided]' when null."""
        state = IntakeState(covers_worldwide_assets=None)
        doc = DocumentGenerator.generate(state)
        assert "Covers Worldwide Assets: [Not yet provided]" in doc

        # When explicitly False
        state_local = IntakeState(covers_worldwide_assets=False)
        doc_local = DocumentGenerator.generate(state_local)
        assert "No (Restricted to assets within primary home jurisdiction)" in doc_local

    def test_5_has_children_false(self):
        """Test 5: Explicit no children status is rendered properly."""
        state = IntakeState(has_children=False, children=[])
        doc = DocumentGenerator.generate(state)
        assert "Status: Declared no children." in doc

    def test_6_has_children_true_with_names(self):
        """Test 6: Children names listed clearly."""
        state = IntakeState(has_children=True, children=["Ananya", "Aditya"])
        doc = DocumentGenerator.generate(state)
        assert "Children Names: Ananya, Aditya" in doc

    def test_7_has_children_true_without_names(self):
        """Test 7: has_children=True but names list empty shows missing names notice."""
        state = IntakeState(has_children=True, children=[])
        doc = DocumentGenerator.generate(state)
        assert "Status: User indicated having children, but names are [Not yet provided]." in doc

    def test_8_partial_executor(self):
        """Test 8: Executor with only name or only relationship."""
        state_name_only = IntakeState(executor=Executor(name="Rahul", relationship=None))
        doc_name_only = DocumentGenerator.generate(state_name_only)
        assert "Executor Name: Rahul" in doc_name_only
        assert "Relationship to Declarant: [Not yet provided]" in doc_name_only

        state_rel_only = IntakeState(executor=Executor(name=None, relationship="Brother"))
        doc_rel_only = DocumentGenerator.generate(state_rel_only)
        assert "Executor Name: [Not yet provided]" in doc_rel_only
        assert "Relationship to Declarant: Brother" in doc_rel_only

    def test_9_specific_gifts(self):
        """Test 9: Specific gifts numbered clearly."""
        state = IntakeState(
            specific_gifts=[
                SpecificGift(recipient="Ananya", item_or_amount="Car"),
            ]
        )
        doc = DocumentGenerator.generate(state)
        assert "1. To Ananya: Car" in doc

    def test_10_additional_wishes(self):
        """Test 10: Additional wishes rendered accurately."""
        state = IntakeState(additional_wishes="Scatter ashes in the ocean.")
        doc = DocumentGenerator.generate(state)
        assert "Scatter ashes in the ocean." in doc

    def test_11_no_hallucinated_information(self):
        """Test 11: Empty state has zero hallucinated values."""
        state = IntakeState()
        doc = DocumentGenerator.generate(state)
        # Should not contain any fabricated names, addresses, or relations
        assert "Rahul" not in doc
        assert "Brother" not in doc
        assert "Spouse" not in doc
        assert "India" not in doc

    def test_12_deterministic_output(self):
        """Test 12: Calling generate multiple times on identical state yields exact identical string."""
        state = IntakeState(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            covers_worldwide_assets=False,
            has_children=False,
            executor=Executor(name="Rahul", relationship="Brother"),
        )
        doc_1 = DocumentGenerator.generate(state)
        doc_2 = DocumentGenerator.generate(state)
        assert doc_1 == doc_2


class TestOrchestratorDocumentIntegration:
    @pytest.fixture
    def setup_orchestrator(self):
        sm = SessionManager()
        llm = MockLLMService()
        orch = ConversationOrchestrator(session_manager=sm, llm_service=llm)
        return sm, orch

    def test_13_orchestrator_returns_updated_document(self, setup_orchestrator):
        """Test 13: Confirmed user input causes orchestrator to return updated draft document."""
        sm, orch = setup_orchestrator
        sm.create_session("sess-doc-1")

        result = orch.handle_user_message("sess-doc-1", "My name is Karan Deshmukh")
        assert "Full Legal Name: Karan Deshmukh" in result.draft_document
        assert "Residential Address: [Not yet provided]" in result.draft_document

        result_2 = orch.handle_user_message("sess-doc-1", "I live in Nagpur")
        assert "Full Legal Name: Karan Deshmukh" in result_2.draft_document
        assert "Residential Address: Nagpur" in result_2.draft_document

    def test_14_ambiguous_input_does_not_change_document(self, setup_orchestrator):
        """Test 14: Ambiguous message does not alter existing draft document."""
        sm, orch = setup_orchestrator
        sm.create_session("sess-doc-2")

        # Initial turn
        r1 = orch.handle_user_message("sess-doc-2", "My name is Karan Deshmukh")
        doc_before = r1.draft_document

        # Ambiguous turn
        r2 = orch.handle_user_message("sess-doc-2", "I want everything covered.")
        assert r2.status == "clarification_needed"
        assert r2.draft_document == doc_before
        assert "Covers Worldwide Assets: [Not yet provided]" in r2.draft_document

    def test_15_contradictory_input_does_not_change_document(self, setup_orchestrator):
        """Test 15: Contradictory message leaves draft document unaltered."""
        sm, orch = setup_orchestrator
        sm.create_session("sess-doc-3")
        sm.update_state("sess-doc-3", IntakeState(full_name="Karan", has_children=False))

        # Baseline draft document
        doc_baseline = DocumentGenerator.generate(sm.get_session("sess-doc-3").state)
        assert "Status: Declared no children." in doc_baseline

        # Trigger contradiction
        r = orch.handle_user_message("sess-doc-3", "My daughter Ananya should receive my car.")
        assert r.status == "contradiction_detected"
        assert r.draft_document == doc_baseline
        assert "Ananya" not in r.draft_document
        assert "Status: Declared no children." in r.draft_document
