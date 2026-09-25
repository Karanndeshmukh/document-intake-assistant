"""
Deterministic validation and business rules engine for Document Intake Assistant.

This module inspects typed LLM extractions against the current IntakeState.
It ensures that:
1. Valid new fields are safely applied to the state.
2. Partial fields (e.g., executor name without relationship) are preserved.
3. Explicit corrections ('IntentType.CORRECTION') overwrite previous values.
4. Contradictions (e.g., 'no children' vs. 'daughter Ananya') are blocked and flagged.
5. Ambiguous statements do not corrupt or mutate state.
6. Unknown fields remain explicitly unknown.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.schemas import (
    Executor,
    ExtractedFields,
    IntakeState,
    IntentType,
    PendingClarification,
    SpecificGift,
)


class ValidationStatus(str, Enum):
    APPLIED = "applied"                    # Successfully applied new or augmented fields
    CORRECTED = "corrected"                # Successfully applied explicit user correction
    CONTRADICTION = "contradiction"        # Contradiction detected; state mutation blocked
    AMBIGUOUS = "ambiguous"                # Statement is ambiguous; state mutation blocked
    INVALID = "invalid"                    # Extraction failed validation rules; state unchanged
    NO_OP = "no_op"                        # No state changes required (e.g. chit-chat or duplicate info)


class ValidationResult(BaseModel):
    status: ValidationStatus
    updated_state: IntakeState
    pending_clarification: Optional[PendingClarification] = None
    applied_fields: List[str] = Field(default_factory=list)
    rejected_fields: List[str] = Field(default_factory=list)
    explanation: str = ""


class ValidationEngine:
    """
    Deterministic rule engine that safely applies ExtractedFields to IntakeState.
    """

    @classmethod
    def validate_and_apply(
        cls,
        current_state: IntakeState,
        extracted: ExtractedFields,
        intent: IntentType = IntentType.INFORM,
        ambiguity_reason: Optional[str] = None,
        contradiction_reason: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validates the extracted fields against the current state and intent.
        Returns a ValidationResult containing either the safely updated state
        or the original state with contradiction/ambiguity details.
        """
        # 0. Check for Internal Extraction Inconsistency (e.g. has_children=False with children populated)
        if extracted.has_children is False and extracted.children and len(extracted.children) > 0:
            return ValidationResult(
                status=ValidationStatus.INVALID,
                updated_state=current_state.model_copy(deep=True),
                explanation="Extraction contained invalid conflicting data (has_children=False with children listed).",
            )

        # 1. Handle Ambiguous Intent
        if intent == IntentType.AMBIGUOUS:
            return ValidationResult(
                status=ValidationStatus.AMBIGUOUS,
                updated_state=current_state.model_copy(deep=True),
                pending_clarification=PendingClarification(
                    field_name="ambiguous_statement",
                    reason=ambiguity_reason or "Statement is ambiguous and needs clarification.",
                ),
                explanation=ambiguity_reason or "Input was ambiguous. State remained untouched.",
            )

        # 2. Handle Off-Topic Intent
        if intent == IntentType.OFF_TOPIC:
            return ValidationResult(
                status=ValidationStatus.NO_OP,
                updated_state=current_state.model_copy(deep=True),
                explanation="Off-topic message. No state changes.",
            )

        # 3. Check for Contradictions Before Mutation
        contradiction = cls._detect_contradiction(current_state, extracted, intent, contradiction_reason)
        if contradiction:
            return ValidationResult(
                status=ValidationStatus.CONTRADICTION,
                updated_state=current_state.model_copy(deep=True),
                pending_clarification=contradiction,
                rejected_fields=[contradiction.field_name],
                explanation=contradiction.reason,
            )

        # 4. Apply State Update (either as Correction or as New/Augmented Info)
        working_state = current_state.model_copy(deep=True)
        applied_fields: List[str] = []

        is_correction = (intent == IntentType.CORRECTION)

        try:
            # Full Name
            if extracted.full_name is not None:
                if current_state.full_name is None or is_correction:
                    if working_state.full_name != extracted.full_name:
                        working_state.full_name = extracted.full_name
                        applied_fields.append("full_name")

            # Home Address
            if extracted.home_address is not None:
                if current_state.home_address is None or is_correction:
                    if working_state.home_address != extracted.home_address:
                        working_state.home_address = extracted.home_address
                        applied_fields.append("home_address")

            # Worldwide Assets
            if extracted.covers_worldwide_assets is not None:
                if current_state.covers_worldwide_assets is None or is_correction:
                    if working_state.covers_worldwide_assets != extracted.covers_worldwide_assets:
                        working_state.covers_worldwide_assets = extracted.covers_worldwide_assets
                        applied_fields.append("covers_worldwide_assets")

            # Children Logic
            # Case A: has_children explicitly provided
            if extracted.has_children is not None:
                if current_state.has_children is None or is_correction:
                    working_state.has_children = extracted.has_children
                    if extracted.has_children is False:
                        working_state.children = []
                    applied_fields.append("has_children")

            # Case B: children list provided
            if extracted.children is not None and len(extracted.children) > 0:
                if working_state.has_children is not False or is_correction:
                    working_state.has_children = True
                    if is_correction:
                        working_state.children = list(dict.fromkeys(extracted.children))
                    else:
                        # Merge new children without duplicates
                        for child in extracted.children:
                            if child not in working_state.children:
                                working_state.children.append(child)
                    if "children" not in applied_fields:
                        applied_fields.append("children")

            # Executor Logic (Merge partial fields)
            if extracted.executor is not None:
                new_exec = extracted.executor
                updated_executor = working_state.executor.model_copy()

                if new_exec.name is not None:
                    if working_state.executor.name is None or is_correction:
                        updated_executor.name = new_exec.name
                        if "executor.name" not in applied_fields:
                            applied_fields.append("executor.name")

                if new_exec.relationship is not None:
                    if working_state.executor.relationship is None or is_correction:
                        updated_executor.relationship = new_exec.relationship
                        if "executor.relationship" not in applied_fields:
                            applied_fields.append("executor.relationship")

                working_state.executor = updated_executor

            # Specific Gifts Logic (Append new gifts)
            if extracted.specific_gifts:
                for gift in extracted.specific_gifts:
                    # Avoid exact duplicate gifts
                    if gift not in working_state.specific_gifts:
                        working_state.specific_gifts.append(gift)
                        if "specific_gifts" not in applied_fields:
                            applied_fields.append("specific_gifts")

            # Additional Wishes
            if extracted.additional_wishes is not None:
                if current_state.additional_wishes is None or is_correction:
                    if working_state.additional_wishes != extracted.additional_wishes:
                        working_state.additional_wishes = extracted.additional_wishes
                        applied_fields.append("additional_wishes")

            # Trigger Pydantic model validation on working_state
            validated_state = IntakeState.model_validate(working_state.model_dump())

        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.INVALID,
                updated_state=current_state.model_copy(deep=True),
                explanation=f"State update failed validation constraints: {str(e)}",
            )

        if not applied_fields:
            return ValidationResult(
                status=ValidationStatus.NO_OP,
                updated_state=current_state.model_copy(deep=True),
                explanation="No new or modified fields to apply.",
            )

        status = ValidationStatus.CORRECTED if is_correction else ValidationStatus.APPLIED
        return ValidationResult(
            status=status,
            updated_state=validated_state,
            applied_fields=applied_fields,
            explanation=f"Applied fields: {', '.join(applied_fields)}",
        )

    @classmethod
    def _detect_contradiction(
        cls,
        current: IntakeState,
        extracted: ExtractedFields,
        intent: IntentType,
        custom_reason: Optional[str],
    ) -> Optional[PendingClarification]:
        """
        Detects conflicts between extracted data and established IntakeState
        when the intent is NOT an explicit correction.
        """
        # If user explicitly marked this as a contradiction
        if intent == IntentType.CONTRADICTION:
            return PendingClarification(
                field_name="general_contradiction",
                reason=custom_reason or "The statement contradicts previously recorded information.",
            )

        # Allow explicit corrections to bypass contradiction rejection
        if intent == IntentType.CORRECTION:
            return None

        # Contradiction Check 1: Children
        # If state says has_children=False, but extraction provides has_children=True or children names
        if current.has_children is False:
            if extracted.has_children is True or (extracted.children and len(extracted.children) > 0):
                return PendingClarification(
                    field_name="has_children",
                    reason="Previously stated you have no children, but now children were mentioned.",
                    current_value=False,
                    proposed_value=extracted.children or True,
                )

        # If state has children listed, but incoming says has_children=False without correction intent
        if current.has_children is True and len(current.children) > 0:
            if extracted.has_children is False:
                return PendingClarification(
                    field_name="has_children",
                    reason=f"Previously recorded children ({', '.join(current.children)}), but now stated no children.",
                    current_value=current.children,
                    proposed_value=False,
                )

        # Contradiction Check 2: Worldwide Assets
        if current.covers_worldwide_assets is not None and extracted.covers_worldwide_assets is not None:
            if current.covers_worldwide_assets != extracted.covers_worldwide_assets:
                return PendingClarification(
                    field_name="covers_worldwide_assets",
                    reason="Conflicting answer on whether worldwide assets are covered.",
                    current_value=current.covers_worldwide_assets,
                    proposed_value=extracted.covers_worldwide_assets,
                )

        # Contradiction Check 3: Executor Name Collision without Correction Intent
        if (
            current.executor.name is not None
            and extracted.executor is not None
            and extracted.executor.name is not None
        ):
            if current.executor.name.lower() != extracted.executor.name.lower():
                return PendingClarification(
                    field_name="executor.name",
                    reason=f"Previously named '{current.executor.name}' as executor, but now named '{extracted.executor.name}'.",
                    current_value=current.executor.name,
                    proposed_value=extracted.executor.name,
                )

        return None
