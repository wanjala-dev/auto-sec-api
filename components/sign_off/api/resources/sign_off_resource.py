"""Output DTOs for the unified sign-off queue API.

Mechanical translation from the kernel's ``SignOffItem`` / ``SignOffDetail``
value objects to JSON-serialisable dicts — no business logic (that lives in the
kernel). Mirrors the reports context's ``api/resources/`` convention.
"""

from __future__ import annotations

from components.sign_off.application.services.sign_off_queue_service import SignOffDetail
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem


class SignOffItemResource:
    """One queue row."""

    @staticmethod
    def from_item(item: SignOffItem) -> dict:
        s = item.receipts_summary
        return {
            "artifact_type": item.artifact_type,
            "artifact_id": item.artifact_id,
            "title": item.title,
            "review_state": item.review_state.value,
            "risk_band": item.risk_band.value,
            "audience": item.audience,
            "workspace_id": item.workspace_id,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "receipts_summary": {
                "unverified_figures": s.unverified_figures,
                "ungrounded_claims": s.ungrounded_claims,
                "voice_flags": s.voice_flags,
                "is_clean": s.is_clean,
            },
        }


class SignOffDetailResource:
    """A single artifact's full detail, including the complete receipts."""

    @staticmethod
    def _receipts(receipts: ReviewerReceipts) -> dict:
        return {
            "figure_checks": [
                {
                    "claim_text": fc.claim_text,
                    "stated_value": fc.stated_value,
                    "source_value": fc.source_value,
                    "verified": fc.verified,
                    "source_ref": fc.source_ref,
                    "contradicted": fc.contradicted,
                    "unverifiable": fc.unverifiable,
                }
                for fc in receipts.figure_checks
            ],
            "claim_provenance": [
                {
                    "claim_text": cp.claim_text,
                    "source_record_ref": cp.source_record_ref,
                    "grounded": cp.grounded,
                }
                for cp in receipts.claim_provenance
            ],
            "voice_flags": [{"span": vf.span, "issue": vf.issue} for vf in receipts.voice_flags],
            "is_clean": receipts.is_clean,
            "has_contradictions": receipts.has_contradictions,
        }

    @classmethod
    def from_detail(cls, detail: SignOffDetail) -> dict:
        return {
            "artifact_type": detail.artifact_type,
            "artifact_id": detail.artifact_id,
            "review_state": detail.review_state.value,
            "risk_band": detail.risk_band.value,
            "workspace_id": detail.workspace_id,
            "target": {
                "audience": detail.target.audience.value,
                "high_stakes": detail.target.high_stakes,
                "escalates": detail.target.escalates,
            },
            "receipts": cls._receipts(detail.receipts),
        }
