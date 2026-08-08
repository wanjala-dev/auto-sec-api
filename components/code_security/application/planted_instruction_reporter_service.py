"""Report AI-targeted instructions planted in repository content as a FINDING.

The novel product signal this pillar can raise that nothing else in the market
does: *"someone planted instructions aimed at an AI assistant inside your
codebase."* The article's Project-4 detection idea (§3.4 adopt #2) applied to our
newest pillar — and, unlike the injection flag on an indexed RAG chunk, this one
is about the CUSTOMER's own repository, so it is a security finding they act on,
not internal telemetry.

Trigger: while triaging a SAST finding, the advisor fetches real file content
through the consent-checked read seam and runs the existing pure heuristic
(``knowledge.domain.value_objects.injection_scan.is_injection_suspected`` —
Django-free by design, reused rather than re-implemented). A hit means the file
around the finding carries instruction-injection shapes. That already forces the
``needs_human`` path (the enforcement control); THIS raises it as its own
finding so it is visible, deduped, lifecycle-tracked, and board-surfaced like
every other finding.

Stays on the proven recipe: emit ``FindingObserved`` (the pillar never writes a
Finding row — owner-persists, ADR 0004) with source
``code_security.planted_instructions``; the findings context dedups on
``(workspace, source, fingerprint)`` and the board handler files the card.
Fail-safe: any error degrades to a log line — raising this signal must never
break the triage it rides along with.

D8 discipline: the finding carries the file location + WHICH heuristic shapes
fired, never the suspicious text itself — copying a planted instruction into the
board card, notifications and every projection would spread the payload.
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

SOURCE = "code_security.planted_instructions"


def report_planted_instructions(
    *,
    workspace_id,
    repo: str,
    path: str,
    commit_sha: str = "",
    rule_id: str = "",
    event_publisher=None,
) -> bool:
    """Raise the planted-instructions finding for ``repo``/``path``. Returns whether
    an event was published (never raises)."""
    if not (workspace_id and repo and path):
        return False
    try:
        from components.shared_kernel.domain.events import FindingObserved
        from components.shared_kernel.domain.security import AssetUrn, Severity

        # Identity: repo + path (NOT the line, NOT the content) — the same planted
        # file re-observed by tomorrow's triage bumps last_seen instead of minting
        # a duplicate; moving the text within the file is still the same problem.
        fingerprint = f"{repo}|planted_instructions|{path}"
        if len(fingerprint) > 255:
            fingerprint = f"{repo}|planted_instructions|p{hashlib.sha256(path.encode()).hexdigest()[:16]}"[:255]

        event = FindingObserved(
            workspace_id=workspace_id,
            source=SOURCE,
            fingerprint=fingerprint,
            asset_urn=AssetUrn.canonical("vcs", f"github:{repo}").value,
            severity=Severity.HIGH.value,
            title=f"AI-targeted instructions found in {path}",
            description=(
                f"Content in {path} matches known prompt-injection shapes — text written to be "
                "read as INSTRUCTIONS by an AI assistant rather than as code or documentation. "
                "Auto-Sec's remediation agent reads this file when proposing fixes; it treats "
                "the content strictly as data and any fix suggested for this file is held for "
                "human review, so the attempt did not influence a pull request. The planted "
                "text itself is deliberately not reproduced here."
            ),
            remediation=(
                f"Open {path} and look for comments or strings addressed to an AI assistant "
                "(e.g. instructions to ignore rules, modify other files, weaken authentication, "
                "or reveal secrets). Determine who introduced them (`git log -p` on the file) and "
                "remove them. If they were not added deliberately by your team, treat this as a "
                "supply-chain compromise of the repository."
            ),
            attributes={
                "repo": repo,
                "path": path,
                "commit_sha": commit_sha,
                "detected_by": "injection_scan_heuristic",
                "triggering_rule_id": rule_id,
                "category": "planted_ai_instructions",
            },
        )

        publisher = event_publisher
        if publisher is None:
            from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
                CeleryEventPublisher,
            )

            publisher = CeleryEventPublisher()
        publisher.publish(event)
        logger.warning(
            "planted_instructions_finding_raised workspace_id=%s repo=%s path=%s rule_id=%s",
            workspace_id,
            repo,
            path,
            rule_id,
        )
        return True
    except Exception:
        logger.exception(
            "planted_instructions_report_failed workspace_id=%s repo=%s path=%s",
            workspace_id,
            repo,
            path,
        )
        return False
