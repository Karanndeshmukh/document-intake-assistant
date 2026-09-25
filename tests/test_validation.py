"""
Unit tests for deterministic validation rules in ValidationEngine.

Tests explicitly cover:
- Test D: Unknown fields remain unknown
- Test E: Valid new information is applied
- Test F: Partial executor information is allowed and safely augmented
- Test G: Explicit correction updates existing state
- Test H: Contradictory child information is detected and blocked
- Test I: Ambiguous information does not mutate state
- Test J: Invalid extracted data does not mutate state
- Test K: Multiple fields can be applied together
- Gifts and wishes collection without data loss
"""

import pytest

from backend.schemas import (
    Executor,
    ExtractedFields,
    IntakeState,
    IntentType,
    SpecificGift,
)
from backend.validation import ValidationEngine, ValidationStatus


class TestValidationEngine:
    def test_d_unknown_fields_remain_unknown(self):
        """
        Test D: Providing only name and address leaves all other fields explicitly None / empty.
        Expected Transition:
        Initial: All None
        Extraction: full_name="Karan", home_address="Nagpur"
        Result: full_name="Karan", home_address="Nagpur", covers_worldwide_assets=None, executor=Executor(None, None)
        """
        initial_state = IntakeState()
        extracted = ExtractedFields(full_name="Karan Deshmukh", home_address="Nagpur")

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.APPLIED
        assert result.updated_state.full_name == "Karan Deshmukh"
        assert result.updated_state.home_address == "Nagpur"
        # Verify strict unknowns:
        assert result.updated_state.covers_worldwide_assets is None
        assert result.updated_state.has_children is None
        assert result.updated_state.children == []
        assert result.updated_state.executor.name is None
        assert result.updated_state.executor.relationship is None

    def test_e_valid_new_information_is_applied(self):
        """
        Test E: Clean extraction applied to blank fields.
        Expected Transition:
        Initial: covers_worldwide_assets=None
        Extraction: covers_worldwide_assets=True
        Result: covers_worldwide_assets=True
        """
        initial_state = IntakeState()
        extracted = ExtractedFields(covers_worldwide_assets=True)

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.APPLIED
        assert result.updated_state.covers_worldwide_assets is True
        assert "covers_worldwide_assets" in result.applied_fields

    def test_f_partial_executor_information_is_allowed(self):
        """
        Test F: Executor name without relationship is allowed and can be augmented later.
        Expected Transitions:
        Step 1:
          Initial: executor=Executor(None, None)
          Extraction: executor=Executor(name="Rahul", relationship=None)
          Result: executor=Executor(name="Rahul", relationship=None) [Relationship remains None!]
        Step 2:
          Initial: executor=Executor(name="Rahul", relationship=None)
          Extraction: executor=Executor(name=None, relationship="Brother")
          Result: executor=Executor(name="Rahul", relationship="Brother") [Name is preserved!]
        """
        # Step 1: Set only executor name
        initial_state = IntakeState()
        extracted_1 = ExtractedFields(executor=Executor(name="Rahul"))

        result_1 = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted_1,
            intent=IntentType.INFORM,
        )
        assert result_1.status == ValidationStatus.APPLIED
        assert result_1.updated_state.executor.name == "Rahul"
        assert result_1.updated_state.executor.relationship is None

        # Step 2: Supply only the missing relationship
        extracted_2 = ExtractedFields(executor=Executor(relationship="Brother"))
        result_2 = ValidationEngine.validate_and_apply(
            current_state=result_1.updated_state,
            extracted=extracted_2,
            intent=IntentType.INFORM,
        )
        assert result_2.status == ValidationStatus.APPLIED
        assert result_2.updated_state.executor.name == "Rahul"
        assert result_2.updated_state.executor.relationship == "Brother"
        assert result_2.updated_state.executor.is_complete

    def test_g_explicit_correction_updates_existing_state(self):
        """
        Test G: Explicit correction updates an already established field.
        Expected Transition:
        Initial: executor=Executor(name="Rahul", relationship="Brother")
        Extraction: executor=Executor(name="Amit"), intent=CORRECTION
        Result: executor=Executor(name="Amit", relationship="Brother")
        """
        initial_state = IntakeState(
            executor=Executor(name="Rahul", relationship="Brother")
        )
        extracted = ExtractedFields(executor=Executor(name="Amit"))

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.CORRECTION,
        )

        assert result.status == ValidationStatus.CORRECTED
        assert result.updated_state.executor.name == "Amit"
        assert result.updated_state.executor.relationship == "Brother"

    def test_h_contradictory_child_information_is_detected(self):
        """
        Test H: When state says has_children=False, mentioning a child is flagged as contradiction
        and DOES NOT mutate the state.
        Expected Transition:
        Initial: has_children=False, children=[]
        Extraction: children=["Ananya"], intent=INFORM
        Result: CONTRADICTION detected, state remains has_children=False, children=[], pending_clarification populated.
        """
        initial_state = IntakeState(has_children=False, children=[])
        extracted = ExtractedFields(children=["Ananya"])

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.CONTRADICTION
        # State must NOT be mutated
        assert result.updated_state.has_children is False
        assert result.updated_state.children == []
        # Clarification must be flagged
        assert result.pending_clarification is not None
        assert result.pending_clarification.field_name == "has_children"
        assert "no children" in result.pending_clarification.reason.lower()

    def test_i_ambiguous_information_does_not_mutate_state(self):
        """
        Test I: Ambiguous user statement (e.g. 'I want everything covered') does NOT mutate state.
        Expected Transition:
        Initial: covers_worldwide_assets=None
        Extraction: intent=AMBIGUOUS, ambiguity_reason="Vague statement"
        Result: AMBIGUOUS status, covers_worldwide_assets remains None.
        """
        initial_state = IntakeState()
        extracted = ExtractedFields()

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.AMBIGUOUS,
            ambiguity_reason="Unclear if 'everything' means worldwide or all local properties.",
        )

        assert result.status == ValidationStatus.AMBIGUOUS
        assert result.updated_state.covers_worldwide_assets is None
        assert result.pending_clarification is not None
        assert "worldwide" in result.pending_clarification.reason.lower()

    def test_j_invalid_extracted_data_does_not_mutate_state(self):
        """
        Test J: Incompatible extraction does not crash and leaves state unmutated.
        """
        initial_state = IntakeState(full_name="Karan")
        # Attempting an illegal combination in extracted fields
        extracted = ExtractedFields(has_children=False, children=["Rohan"])

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.INVALID
        assert result.updated_state.full_name == "Karan"
        assert result.updated_state.has_children is None

    def test_k_multiple_fields_can_be_applied_together(self):
        """
        Test K: Single turn with multiple fields extracts and applies all valid fields simultaneously.
        Example user message:
        'My name is Karan Deshmukh. I live in Nagpur. I don't have children and my brother Rahul will be my executor.'
        Expected Transition:
        Initial: All None
        Result:
          full_name = 'Karan Deshmukh'
          home_address = 'Nagpur'
          has_children = False
          children = []
          executor = Executor(name='Rahul', relationship='brother')
        """
        initial_state = IntakeState()
        extracted = ExtractedFields(
            full_name="Karan Deshmukh",
            home_address="Nagpur",
            has_children=False,
            executor=Executor(name="Rahul", relationship="Brother"),
        )

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.APPLIED
        assert result.updated_state.full_name == "Karan Deshmukh"
        assert result.updated_state.home_address == "Nagpur"
        assert result.updated_state.has_children is False
        assert result.updated_state.children == []
        assert result.updated_state.executor.name == "Rahul"
        assert result.updated_state.executor.relationship == "Brother"
        assert set(result.applied_fields) == {
            "full_name",
            "home_address",
            "has_children",
            "executor.name",
            "executor.relationship",
        }

    def test_specific_gifts_and_additional_wishes(self):
        """Gifts append cleanly and additional wishes are stored."""
        initial_state = IntakeState()
        extracted = ExtractedFields(
            specific_gifts=[
                SpecificGift(recipient="Ananya", item_or_amount="Car"),
                SpecificGift(recipient="Rohan", item_or_amount="10000 USD"),
            ],
            additional_wishes="Scatter ashes in Himalayas",
        )

        result = ValidationEngine.validate_and_apply(
            current_state=initial_state,
            extracted=extracted,
            intent=IntentType.INFORM,
        )

        assert result.status == ValidationStatus.APPLIED
        assert len(result.updated_state.specific_gifts) == 2
        assert result.updated_state.additional_wishes == "Scatter ashes in Himalayas"
