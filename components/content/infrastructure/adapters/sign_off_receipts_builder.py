"""Shared receipts-building helper for the content sign-off adapters.

Both the newsletter and writing-draft adapters build their
:class:`ReviewerReceipts` the same way the Phase-2 financial-report adapter
does: re-run the deterministic :class:`FaithfulnessVerifier` (a cross-context
*domain* service — allowed) against the artifact's produced HTML using the
data it was built from as the grounding corpus, then map:

- every ``unsupported_number`` -> an *unverifiable* :class:`FigureCheck`
  (amber; ``source_value=None`` so it reads as "couldn't confirm", never
  "the source contradicts"), and
- every ``unsupported_name`` -> an *ungrounded* :class:`ClaimProvenance`.

This mirrors ``financial_report_sign_off_adapter``'s mapping exactly — kept
here (content-internal) rather than imported cross-context, since importing
another context's infrastructure is forbidden.
"""

from __future__ import annotations

from components.agents.domain.services.faithfulness_verifier import FaithfulnessVerifier
from components.sign_off.domain.value_objects.reviewer_receipts import (
    ClaimProvenance,
    FigureCheck,
    ReviewerReceipts,
)


def build_receipts_from_html(generated_html: str, grounding_texts: list[str]) -> ReviewerReceipts:
    """Run the faithfulness verifier and normalise its output into receipts."""
    result = FaithfulnessVerifier().verify(
        generated_html=generated_html or "",
        grounding_texts=grounding_texts,
    )
    figure_checks = tuple(
        # No source value found -> unverifiable (amber), not contradicted.
        FigureCheck(claim_text=token, stated_value=token, source_value=None, verified=False)
        for token in result.unsupported_numbers
    )
    claim_provenance = tuple(
        ClaimProvenance(claim_text=name, source_record_ref=None, grounded=False)
        for name in result.unsupported_names
    )
    return ReviewerReceipts(
        figure_checks=figure_checks,
        claim_provenance=claim_provenance,
    )


def collect_grounding_values(*sources) -> list[str]:
    """Flatten one or more dict/list sources into stringified leaf facts the
    verifier can check the produced copy's figures against."""
    texts: list[str] = []
    for source in sources:
        _collect_values(source, texts)
    return texts


def _collect_values(value, sink: list[str]) -> None:
    """Recursively flatten dict/list values into stringified leaves."""
    if isinstance(value, dict):
        for nested in value.values():
            _collect_values(nested, sink)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _collect_values(nested, sink)
    elif value is not None and not isinstance(value, bool):
        sink.append(str(value))
