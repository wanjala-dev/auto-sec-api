"""Port: retrieve VETTED past remediations to GROUND a triage suggestion (ADR 0012 P4).

This is the read half of Remediation Memory. The triage advisor calls it BEFORE it
proposes a fix, to retrieve the team's own proven fixes for the same class of
finding and ground its suggestion in them (grounded, not hallucinated). It is the
public application surface the advisor (in ``integrations``) consumes — a read-only
cross-context reach (architecture skill C3), never a direct import of remediation's
models.

Two invariants this port exists to enforce (ADR 0012 D2 + D4):

- **D4 — tenant isolation is MANDATORY.** ``workspace_id`` is a required argument,
  not an optional filter; retrieval NEVER crosses a workspace boundary. A missing/
  empty ``workspace_id`` returns ``[]`` (fail-closed) — it must never fall back to
  an unscoped search.
- **D2 — retrieval GROUNDS, it never AUTHORIZES.** What comes back is *candidate
  grounding*, not a decision. The advisor's suggestion is STILL run through the
  full verification path (``validate_patch`` / ``verify_suggestion``) and the
  sign-off gate exactly as a from-scratch suggestion is. A retrieved prior does not
  skip any guardrail.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# The ``ai_embedding_chunks`` metadata discriminator for Remediation Memory rows.
# Embed-on-capture stamps it; retrieval filters on it (with ``workspace_id``) so a
# remediation query can NEVER pull a workspace-snapshot / document chunk, and a
# workspace-snapshot query (which filters ``source``) can never pull a remediation
# chunk. Both directions fail closed: a chunk lacking the key yields SQL NULL,
# which fails the ``=`` predicate.
REMEDIATION_CHUNK_TYPE = "remediation_entry"


@dataclass(frozen=True)
class RemediationGroundingDTO:
    """One vetted prior fix, retrieved to ground a new suggestion.

    Carries the RAW fix code + language (never rendered HTML — ADR 0012 D3) and the
    structured retrieval keys, so the advisor can render "here is how this team
    fixed this class of finding before" into its prompt as reference material.
    """

    finding_kind: str
    language: str
    title: str
    summary: str
    code: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    # ``score`` is the vector SIMILARITY of this candidate to the query. ``rating``
    # is the entry's DERIVED outcome rating (P5); the adapter blends the two to
    # ORDER results (proven fixes rank above unproven ones of like similarity), and
    # carries both here for transparency.
    score: float = 0.0
    rating: int = 0


class RemediationRetrievalPort(ABC):
    @abstractmethod
    def retrieve_grounding(
        self,
        *,
        workspace_id: str,
        finding_kind: str,
        query_text: str,
        top_k: int = 3,
    ) -> list[RemediationGroundingDTO]:
        """Return up to *top_k* vetted prior fixes for *workspace_id*, ranked by
        relevance to *query_text*, scoped to *finding_kind* (the class of finding).

        Always workspace-filtered at the data layer (D4). An empty *workspace_id*
        or *query_text* returns ``[]``. Retrieval failures degrade to ``[]`` — a
        cold library must never block or fail triage; it simply grounds nothing.
        """
        ...
