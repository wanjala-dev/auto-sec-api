"""Shared grounding helper — inject the team's VETTED prior fixes into an advisor prompt.

This is the seam that turns Remediation Memory (ADR 0012) from a store into a loop:
BEFORE either triage advisor (``LogFixAdvisor`` / ``LogPatchAdvisor``) proposes a
fix, it calls :func:`retrieve_grounding_block` to pull the workspace's own proven
fixes for the same class of finding, and folds them into its prompt as reference
material. Both advisors do the SAME retrieve-and-render, so it lives here ONCE
(dry-reuse) rather than being copy-pasted per advisor.

Discipline this helper enforces (ADR 0012 D2 + D4):

- **D4 — tenant isolation.** It only ever asks the :class:`RemediationRetrievalPort`,
  which filters ``workspace_id`` at the data layer. A missing workspace yields no
  grounding — never an unscoped search.
- **D2 — grounds, never authorizes.** It returns PROMPT TEXT, nothing else. The
  suggestion the model then produces is STILL run through the advisor's guardrail
  (``verify_suggestion`` / ``validate_patch``) and the sign-off gate. Retrieved
  priors are framed explicitly as *reference*, never as an instruction to emit
  verbatim — a poisoned/irrelevant prior cannot push an unverified fix through.
- **Never a gate on triage.** Any failure (cold library, retrieval error) degrades
  to an empty block, so the advisor behaves exactly as it does today. Grounding is
  an enhancement, never a dependency.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# How many prior fixes to fold in — small on purpose: the corpus is high-signal
# (only gated, applied, resolved fixes) and prompt budget is finite.
_DEFAULT_TOP_K = 3
# Cap the rendered code per prior so a long fix can't dominate the advisor's prompt.
_MAX_CODE_CHARS = 1_200


def finding_kind_from_source_type(source_type: str) -> str:
    """Derive the retrieval ``finding_kind`` from a board ``source_type``.

    Mirrors the capture side (``board_finding_facts_repository._derive_kind``): the
    ``ai.`` prefix is stripped, so ``ai.log_watch`` → ``log_watch``. The two MUST
    agree or the finding_kind filter narrows to nothing.
    """
    st = source_type or ""
    return st[3:] if st.startswith("ai.") else st


def retrieve_grounding_block(
    *,
    workspace_id: str,
    source_type: str,
    query_text: str,
    top_k: int = _DEFAULT_TOP_K,
    retrieval=None,
) -> str:
    """Return a prompt block of the workspace's vetted prior fixes, or ``""``.

    ``retrieval`` is an injected :class:`RemediationRetrievalPort` (tests wire a
    fake); production resolves it lazily through the remediation application
    provider (a cross-context *application* reach — never a remediation-infra
    import). Empty ``workspace_id`` / ``query_text`` → ``""`` (D4 fail-closed).
    """
    if not (workspace_id and str(workspace_id).strip()):
        return ""
    if not (query_text or "").strip():
        return ""

    try:
        port = retrieval or _default_retrieval()
        grounding = port.retrieve_grounding(
            workspace_id=str(workspace_id),
            finding_kind=finding_kind_from_source_type(source_type),
            query_text=query_text,
            top_k=top_k,
        )
    except Exception:
        logger.exception("remediation_grounding_failed workspace_id=%s", workspace_id)
        return ""

    return _render(grounding)


def _default_retrieval():
    from components.remediation.application.providers.remediation_provider import (
        build_remediation_retrieval,
    )

    return build_remediation_retrieval()


def _render(grounding) -> str:
    """Render retrieved priors into a bounded, clearly-framed prompt block."""
    if not grounding:
        return ""
    lines = [
        "PRIOR VERIFIED FIXES from this team's Remediation Memory — fixes that passed "
        "sign-off, were applied, and resolved their finding. Use them ONLY as grounding "
        "for a MINIMAL, correct fix to the CURRENT finding; do not copy one verbatim, and "
        "do not weaken the fix to match a prior. If none is relevant, ignore them.",
    ]
    for i, g in enumerate(grounding, start=1):
        code = (g.code or "").strip()
        if len(code) > _MAX_CODE_CHARS:
            code = code[:_MAX_CODE_CHARS] + "\n… (truncated)"
        header = f"[{i}] {g.title or g.finding_kind or 'prior fix'}"
        if g.summary:
            header += f" — {g.summary}"
        lines.append(header)
        if code:
            lines.append(f"```{g.language or ''}\n{code}\n```")
    return "\n".join(lines) + "\n\n"
