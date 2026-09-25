"""
Document Generator for Personal Wishes Document.

Converts confirmed IntakeState into a formatted, human-readable draft document.
This engine is 100% deterministic, never uses an LLM, and never invents missing information.
All unknown or missing fields are explicitly identified as 'Not yet provided'.
"""

from typing import List
from backend.schemas import IntakeState


class DocumentGenerator:
    """
    Renders structured IntakeState into a standard Personal Wishes Document.
    """

    HEADER_DISCLAIMER = (
        "============================================================\n"
        "                PERSONAL WISHES DOCUMENT                    \n"
        "                  [DRAFT INTAKE COPY]                       \n"
        "============================================================\n"
        "IMPORTANT NOTICE:\n"
        "1. FICTIONAL DOCUMENT - CREATED FOR DEMONSTRATION PURPOSES.\n"
        "2. NOT LEGAL ADVICE - THIS IS NOT A BINDING WILL OR LEGAL INSTRUMENT.\n"
        "============================================================\n"
    )

    @classmethod
    def generate(cls, state: IntakeState) -> str:
        """
        Generates the formatted text draft from the given IntakeState.
        """
        sections: List[str] = [cls.HEADER_DISCLAIMER]

        # Section 1: Personal Information
        full_name = state.full_name if state.full_name else "[Not yet provided]"
        home_address = state.home_address if state.home_address else "[Not yet provided]"
        sections.append(
            "1. PERSONAL INFORMATION\n"
            f"   - Full Legal Name: {full_name}\n"
            f"   - Residential Address: {home_address}\n"
        )

        # Section 2: Asset Jurisdiction
        if state.covers_worldwide_assets is True:
            worldwide_status = "Yes (Covers assets worldwide across all jurisdictions)"
        elif state.covers_worldwide_assets is False:
            worldwide_status = "No (Restricted to assets within primary home jurisdiction)"
        else:
            worldwide_status = "[Not yet provided]"

        sections.append(
            "2. ASSET JURISDICTION & SCOPE\n"
            f"   - Covers Worldwide Assets: {worldwide_status}\n"
        )

        # Section 3: Children & Dependents
        if state.has_children is False:
            children_text = "   - Status: Declared no children."
        elif state.has_children is True:
            if state.children:
                formatted_kids = ", ".join(state.children)
                children_text = f"   - Children Names: {formatted_kids}"
            else:
                children_text = "   - Status: User indicated having children, but names are [Not yet provided]."
        else:
            children_text = "   - Status: [Not yet provided]"

        sections.append(
            "3. FAMILY & DEPENDENTS\n"
            f"{children_text}\n"
        )

        # Section 4: Executor Appointment
        exec_name = state.executor.name if state.executor.name else "[Not yet provided]"
        exec_rel = state.executor.relationship if state.executor.relationship else "[Not yet provided]"

        sections.append(
            "4. APPOINTED EXECUTOR\n"
            f"   - Executor Name: {exec_name}\n"
            f"   - Relationship to Declarant: {exec_rel}\n"
        )

        # Section 5: Specific Gifts & Bequests
        if state.specific_gifts:
            gift_lines = []
            for i, gift in enumerate(state.specific_gifts, 1):
                gift_lines.append(f"   {i}. To {gift.recipient}: {gift.item_or_amount}")
            gifts_text = "\n".join(gift_lines)
        else:
            gifts_text = "   - None specified [Optional]."

        sections.append(
            "5. SPECIFIC GIFTS & BEQUESTS\n"
            f"{gifts_text}\n"
        )

        # Section 6: Additional Wishes
        if state.additional_wishes:
            wishes_text = f"   {state.additional_wishes}"
        else:
            wishes_text = "   - None specified [Optional]."

        sections.append(
            "6. ADDITIONAL INSTRUCTIONS & WISHES\n"
            f"{wishes_text}\n"
        )

        # Footer
        sections.append(
            "============================================================\n"
            "                      END OF DRAFT                          \n"
            "============================================================"
        )

        return "\n".join(sections)
