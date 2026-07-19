"""``EvalExample`` — one labeled eval case derived from a reviewer decision.

Phase 6c of the Verification-Assisted Sign-Off Spine (SEE-190). A human
sign-off decision (approve / request-changes / reject) on an AI-generated
artifact is turned into a durable, provenance-tracked eval example so the
content generators can be measured against real reviewer outcomes.

Pure domain — no Django, no ORM. The persistence app
(``infrastructure/persistence/prompt_eval``) stores these; the Django
repository (``DjangoEvalExampleRepository``) maps rows <-> this VO.

The label schema:

- ``feedback_decision`` — the eval label (see :class:`FeedbackDecision`):
  a careful RED-band override becomes a POSITIVE example
  (``APPROVED_OVERRIDE``); ``changes_requested`` / ``rejected`` become
  NEGATIVE examples whose codes + note say what the generator got wrong.
  Rubber-stamp GREEN/AMBER approvals are dropped upstream (they carry no
  signal), so ``APPROVED_OVERRIDE`` is the only positive label stored.
- ``input_data`` — the grounding snapshot the generator should have been
  faithful to, plus the prompt id, captured from the artifact at decision
  time.
- ``expected_output`` — the reviewer's verdict rubric (decision + codes +
  note), plus, for negative examples, the generated content that was
  rejected so the eval can see what "wrong" looked like.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FeedbackDecision(str, Enum):
    """The eval label a stored example carries.

    Derived from the queue's review token by the record use case's label
    policy — NOT a 1:1 copy of it (a rubber-stamp ``approved`` never
    reaches here; a careful RED-band ``approved`` maps to
    ``APPROVED_OVERRIDE``).
    """

    APPROVED_OVERRIDE = "approved_override"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class ExampleSource(str, Enum):
    """Where an eval example came from."""

    SIGN_OFF_FEEDBACK = "sign_off_feedback"


@dataclass(frozen=True)
class EvalExample:
    """An immutable labeled eval case.

    Mirrors the ``PromptEvalExample`` persistence columns minus the
    ``created_at`` / ``updated_at`` timestamps (those are DB-owned).
    """

    dataset_name: str
    case_id: str
    category: str
    goal: str
    feedback_decision: FeedbackDecision
    artifact_type: str
    artifact_id: str
    input_data: dict = field(default_factory=dict)
    expected_output: dict = field(default_factory=dict)
    source_type: ExampleSource = ExampleSource.SIGN_OFF_FEEDBACK
    feedback_codes: list[str] = field(default_factory=list)
    feedback_note: str = ""
    risk_band: str = ""
    reviewer_id: str = ""
    workspace_id: str = ""

    def __post_init__(self) -> None:
        if not self.dataset_name:
            raise ValueError("EvalExample requires a dataset_name")
        if not self.case_id:
            raise ValueError("EvalExample requires a case_id")
        if not self.artifact_type:
            raise ValueError("EvalExample requires an artifact_type")
        if not self.artifact_id:
            raise ValueError("EvalExample requires an artifact_id")
