"""The per-artifact adapter contract.

Each AI-generating / template context (newsletter, report, workflow-email,
blog, grant draft, budget-apply) implements this once, against its own existing
status field + data, and registers it with the SignOffRegistry. The kernel then
treats every artifact type uniformly — one queue, one state machine, one set of
receipts.

State persistence is owned by the adapter (it reads/writes the artifact's own
status column); the kernel never imports another context's ORM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem
from components.sign_off.domain.value_objects.sign_off_target import SignOffTarget


class SignOffPort(ABC):
    @abstractmethod
    def artifact_type(self) -> str:
        """Stable identifier for this artifact kind, e.g. 'newsletter'."""

    @abstractmethod
    def get_state(self, artifact_id: str) -> ReviewState:
        """Current review state of the artifact."""

    @abstractmethod
    def set_state(self, artifact_id: str, state: ReviewState) -> None:
        """Persist a new review state (the adapter maps it onto its own status)."""

    @abstractmethod
    def build_receipts(self, artifact_id: str) -> ReviewerReceipts:
        """Run the verification signal (faithfulness + provenance + voice) and
        return the normalized receipts the reviewer will see."""

    @abstractmethod
    def target(self, artifact_id: str) -> SignOffTarget:
        """Who the artifact is headed for + whether it's high-stakes."""

    @abstractmethod
    def workspace_id(self, artifact_id: str) -> str | None:
        """Workspace the artifact belongs to.

        Used by the queue API to enforce workspace membership (the kernel
        never resolves a foreign context's ORM — the adapter does) and by the
        queue audit adapter to scope its audit rows.
        """

    # ── Unified queue surface (Phase 6a) ─────────────────────────────────────

    @abstractmethod
    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        """Return every artifact of this type in the workspace still awaiting a
        human decision (review state PENDING or CHANGES_REQUESTED), as
        normalized queue rows.

        The adapter computes each row's risk band itself
        (``assign_band(build_receipts, target)``) — the kernel only merges +
        sorts the rows returned across all adapters.
        """

    @abstractmethod
    def approve(
        self, artifact_id: str, *, actor_id: str, override_reason: str | None = None
    ) -> None:
        """Perform the context's real approve action — send / publish / dispatch
        / resume — delegating to that context's EXISTING use case. The kernel
        has already enforced the RED-band override-reason gate before calling."""

    @abstractmethod
    def request_changes(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        """Send the artifact back for changes (context-specific effect)."""

    @abstractmethod
    def reject(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        """Reject the artifact (context-specific effect — archive / fail)."""

    # ── Feedback → eval capture (Phase 6c) ───────────────────────────────────

    def capture_for_eval(self, artifact_id: str) -> dict | None:
        """Snapshot the AI-generated output + its grounding for an eval example.

        Returns ``{"generated_content": str, "grounding_texts": list[str],
        "prompt_id": str}`` — the produced copy, the facts it should have been
        faithful to, and the generator's prompt id — or ``None`` when the
        artifact type carries no capturable AI output.

        NON-abstract on purpose: only the AI-generating adapters (newsletter,
        writing draft) implement it; every other adapter (workflow-email,
        budget-apply, …) inherits this ``None`` default so a decision on it
        yields a metadata-only eval example rather than forcing a stub.
        """
        return None
