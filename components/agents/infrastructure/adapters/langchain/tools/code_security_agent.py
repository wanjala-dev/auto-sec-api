"""Code-security agent tools — the consumer half of the SAST pipeline (ADR 0019 P2).

The Opengrep scan (P1) lands findings in the SSOT; the board handler surfaces the
high/critical ones as cards routed to the ``code_security_agent``. These tools let
that specialist (dispatched by the finding router, or driven interactively) answer
repo-risk questions from the pillar's own deterministic reads, and triage each
pending SAST finding: ground a minimal fix suggestion on the REAL file content at
the scanned commit, comment it on the card, and move the card into the Triage
column — the exact ``process_pending_finding`` choreography every board-acting
specialist shares (advise → grounded-verify → row-locked comment/move/stamp +
provenance).

Read tools wrap EXISTING code_security use cases/providers (no new persistence,
no LLM): repo risk ranking, scan status, scan history, and the SSOT findings list.
"""

from __future__ import annotations

import json
import logging

from components.agents.infrastructure.adapters.langchain.tools import _finding_processing as fp
from components.shared_kernel.domain.triage import SOURCE_CODE_SECURITY as _CODE_SECURITY_SOURCE

logger = logging.getLogger(__name__)

_SSOT_SOURCE = "code_security.opengrep"
TRIAGE_COLUMN_TITLE = "Triage"


def _parse(input_str: str, default_key: str = "repo") -> dict:
    raw = (input_str or "").strip()
    try:
        data = json.loads(raw) if raw.startswith("{") else ({default_key: raw} if raw else {})
    except (ValueError, TypeError):
        data = {default_key: raw}
    return data if isinstance(data, dict) else {}


def rank_repos_by_risk(agent, input_str: str = "") -> str:
    """READ — severity-weighted risk ranking of the workspace's scannable repos."""
    from components.code_security.application.use_cases.rank_repos_by_risk_use_case import (
        RankReposByRiskUseCase,
    )

    rows = RankReposByRiskUseCase().execute(workspace_id=agent.workspace_id)
    if not rows:
        return "No scannable repos — connect a VCS integration and allowlist repos first."
    return json.dumps(rows)


def get_repo_scan_status(agent, input_str: str = "") -> str:
    """READ — per-repo scan provenance (last scan, status, in-flight, cooldown)."""
    from components.code_security.application.use_cases.list_repo_scan_status_use_case import (
        ListRepoScanStatusUseCase,
    )
    from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
        COOLDOWN_SECONDS,
    )

    rows = ListRepoScanStatusUseCase().execute(workspace_id=agent.workspace_id, cooldown_seconds=COOLDOWN_SECONDS)
    if not rows:
        return "No scannable repos — connect a VCS integration and allowlist repos first."
    return json.dumps(rows, default=str)


def get_scan_history(agent, input_str: str = "") -> str:
    """READ — recent per-repo scan snapshots (severity counts, newest first)."""
    from components.code_security.application.providers.snapshot_provider import (
        list_recent_snapshots,
    )

    repo = (_parse(input_str).get("repo") or "").strip()
    rows = [
        {
            "repo": row.repo,
            "commit_sha": (row.commit_sha or "")[:12],
            "scanned_at": row.created_at.isoformat() if row.created_at else "",
            "total_findings": row.total_findings,
            "critical": row.critical_count,
            "high": row.high_count,
            "medium": row.medium_count,
            "low": row.low_count,
        }
        for row in list_recent_snapshots(agent.workspace_id, repo=repo)
    ]
    if not rows:
        return "No completed code-security scans yet" + (f" for {repo}." if repo else ".")
    return json.dumps(rows)


def get_repo_findings(agent, input_str: str = "") -> str:
    """READ — open SAST findings from the findings SSOT (optionally per repo)."""
    from components.findings.application.providers.finding_provider import FindingProvider

    data = _parse(input_str)
    repo = (data.get("repo") or "").strip()
    try:
        limit = max(1, min(int(data.get("limit") or 20), 50))
    except (TypeError, ValueError):
        limit = 20

    store = FindingProvider.build_finding_store()
    findings = store.list_findings(
        agent.workspace_id, status="open", source=_SSOT_SOURCE, limit=200 if repo else limit, offset=0
    )
    rows = []
    for finding in findings:
        attrs = finding.attributes or {}
        if repo and attrs.get("repo") != repo:
            continue
        rows.append(
            {
                "finding_id": str(finding.id),
                "severity": finding.severity.value,
                "rule_id": attrs.get("rule_id", ""),
                "repo": attrs.get("repo", ""),
                "path": attrs.get("path", ""),
                "start_line": attrs.get("start_line", 0),
                "title": (finding.title or "")[:160],
            }
        )
        if len(rows) >= limit:
            break
    if not rows:
        return "No open code-security findings" + (f" for {repo}." if repo else ".")
    return json.dumps(rows)


def list_pending_code_findings(agent, input_str: str = "") -> str:
    """READ — SAST findings on the board not yet triaged."""
    pending = fp.pending_findings_qs(agent.workspace_id, _CODE_SECURITY_SOURCE)
    if not pending:
        return "No pending code-security findings to triage."
    rows = []
    for t in pending[:20]:
        payload = (t.metadata or {}).get("payload") or {}
        rows.append(
            {
                "task_id": str(t.id),
                "title": t.title[:120],
                "rule_id": payload.get("rule_id") or "",
                "repo": payload.get("repo") or "",
                "path": payload.get("path") or "",
                "start_line": payload.get("start_line") or 0,
                "severity": payload.get("severity") or "",
            }
        )
    return json.dumps(rows)


def triage_code_finding(agent, input_str: str) -> str:
    """REVERSIBLE_WRITE — triage one pending SAST finding: ground a minimal fix
    suggestion (before/after snippet) on the real file at the scanned commit,
    comment it, move the card to Triage, and record the trace + provenance.

    Same board choreography + concurrency guard + grounded-verification loop as
    every specialist (via ``process_pending_finding``); this supplies only the
    SAST advisor (``SastFixAdvisor``), the comment, and the payload fields. The
    ``finding_verifier``'s code_security branch grades the suggestion against the
    rule/file/snippet anchors; an ungrounded one is re-advised once, then LABELED
    ``unverified`` with the named gap — its draft PR still opens, marked
    [UNVERIFIED] (the label downgrades, it never withholds the artifact).
    """
    from components.code_security.application.planted_instruction_reporter_service import (
        report_planted_instructions,
    )
    from components.code_security.application.sast_fix_advisor_service import SastFixAdvisor

    advisor = SastFixAdvisor()
    # One report per triage call even though the advisor may run twice (the
    # grounded re-advise) — the SSOT would dedup anyway, but no need to publish
    # the same event twice.
    reported: dict[str, bool] = {}

    def advise(payload, feedback=""):
        suggestion = advisor.suggest(
            rule_id=str(payload.get("rule_id") or ""),
            path=str(payload.get("path") or ""),
            start_line=int(payload.get("start_line") or 0),
            end_line=int(payload.get("end_line") or 0),
            snippet=str(payload.get("snippet") or ""),
            message=str(payload.get("message") or payload.get("signal") or ""),
            repo=str(payload.get("repo") or ""),
            commit_sha=str(payload.get("commit_sha") or ""),
            workspace_id=str(agent.workspace_id),
            feedback=feedback,
        )
        # Product-first signal: repository content carrying AI-targeted
        # instructions becomes its own finding (deduped + lifecycle-tracked in
        # the SSOT), not just a silent needs_human downgrade on this card.
        if suggestion is not None and suggestion.source_flagged and not reported.get("done"):
            reported["done"] = report_planted_instructions(
                workspace_id=agent.workspace_id,
                repo=str(payload.get("repo") or ""),
                path=str(payload.get("path") or ""),
                commit_sha=str(payload.get("commit_sha") or ""),
                rule_id=str(payload.get("rule_id") or ""),
            )
        return suggestion

    def suggestion_text(suggestion):
        # The grounding surface the verifier checks against the rule/file/snippet
        # anchors — includes the fix snippet so an anchored patch counts.
        return f"{suggestion.likely_cause} {suggestion.suggested_fix} {suggestion.fix_before}"

    def build_comment(suggestion):
        if suggestion is None:
            return (
                "🛠 Code-security agent reviewed this finding but could not derive a "
                "confident fix from the rule and file alone — needs a human eye."
            )
        comment = (
            f"🛠 Code-security agent analysed this finding.\n\n"
            f"Why it matters: {suggestion.likely_cause}\n\n"
            f"Suggested fix: {suggestion.suggested_fix}\n\n"
        )
        if (suggestion.fix_before or "").strip() and (suggestion.fix_after or "").strip():
            comment += f"Before:\n```\n{suggestion.fix_before}\n```\nAfter:\n```\n{suggestion.fix_after}\n```\n\n"
        if suggestion.source_flagged:
            comment += (
                "⚠️ The source file around this finding contains text shaped like "
                "INSTRUCTIONS TO AN AI ASSISTANT (prompt-injection heuristic hit). The "
                "suggestion was produced treating that content strictly as data. Any "
                "draft PR opened from it is clearly labeled UNVERIFIED — inspect the "
                "file for planted instructions and review the patch carefully before "
                "merging.\n\n"
            )
        return comment + f"Confidence: {suggestion.confidence}."

    def apply_payload(payload, suggestion):
        from components.code_security.domain.fix_confidence import confidence_for

        payload["probable_cause"] = suggestion.likely_cause
        payload["suggested_fix"] = suggestion.suggested_fix
        payload["confidence"] = suggestion.confidence
        payload["fix_before"] = suggestion.fix_before
        payload["fix_after"] = suggestion.fix_after
        # Measured per-RULE confidence (#117 step 3) — a different fact from the
        # two labels already on this payload: ``confidence`` is the model
        # grading itself, ``verification`` is this one patch grounded against
        # this one finding. This tier says how the advisor has historically
        # SCORED on this rule against the frozen corpus, which is the only one
        # of the three that could have flagged the PR #866 failure (grounded,
        # in-scope, parsed — and semantically wrong). A label, never a gate:
        # the draft PR opens regardless (standing rule); only the unattended
        # auto-fix tier reads ``tier == "proven"`` as permission.
        payload["fix_confidence"] = confidence_for(str(payload.get("rule_id") or ""), model=suggestion.model).as_label()
        if suggestion.source_flagged:
            # Untrusted-content control, as a LABEL: repository content that trips
            # the injection heuristic downgrades the fix to UNVERIFIED with the
            # named gap — the draft PR still opens (it cannot merge itself; the
            # mechanical ``validate_patch_scope`` guard still fail-closes any
            # patch that reaches outside the flagged lines), it is just never
            # presented as trustworthy.
            payload["source_flagged"] = True
            payload["needs_human"] = True
            payload["verification"] = "unverified"
            payload["verification_gap"] = (
                "The source file contains text shaped like instructions to an AI assistant "
                "(possible prompt injection planted in the repository) — review this patch "
                "carefully before merging; treat the file's content as untrusted."
            )
            payload["needs_human_reason"] = payload["verification_gap"]

    def describe_action(suggestion):
        if suggestion is None:
            return "reviewed; no confident fix from the rule and file"
        if suggestion.source_flagged:
            return (
                f"suggested a code fix ({suggestion.confidence} confidence); "
                "held for human review — the source file carries AI-targeted instructions"
            )
        return f"suggested a code fix ({suggestion.confidence} confidence)"

    return fp.process_pending_finding(
        agent,
        input_str,
        source_type=_CODE_SECURITY_SOURCE,
        column_title=TRIAGE_COLUMN_TITLE,
        acting_agent="code_security_agent",
        advise=advise,
        build_comment=build_comment,
        apply_payload=apply_payload,
        describe_action=describe_action,
        suggestion_text=suggestion_text,
        # The PROPOSED code, graded separately from the grounding text above
        # (which contains the offending line by design). This is what the
        # remediation anti-patterns run against — ADR 0019 D5.
        patch_text=lambda suggestion: suggestion.fix_after,
    )


# --- Repository reads (ADR 0025 Phase 2) -----------------------------------
#
# The specialist could triage a finding but not READ the project it was fixing.
# Its seven tools ranked repos, listed findings and opened PRs; not one of them
# could answer "where does this codebase get its signing key?". Asked to verify a
# JWT signature it therefore invented `fetch_jwks_key` (PR #326) — a tool-inventory
# failure that two rounds of prompt work could not fix, because no wording makes a
# model know a file it cannot open.
#
# All three are READ-ONLY and pass through the same consent boundary as the scan:
# a repo off the connection's `repo_allowlist` never reaches the VCS API, and every
# failure degrades to an empty result rather than ending the run.


def read_repo_file(agent, input_str: str) -> str:
    """Read one file from an allowlisted repo. Input: {"repo","path","ref"?}."""
    from components.integrations.application.providers.vcs_scan_access_provider import (
        read_repo_file as _read,
    )

    data = _parse(input_str)
    repo, path = (data.get("repo") or "").strip(), (data.get("path") or "").strip()
    if not repo or not path:
        return json.dumps({"ok": False, "error": "repo and path are required"})
    content = _read(workspace_id=agent.workspace_id, repo=repo, path=path, ref=(data.get("ref") or "").strip())
    if content is None:
        return json.dumps({"ok": False, "error": f"could not read {path} (not allowlisted, missing, or unreadable)"})
    # Cap the body: a large file would evict the finding's own evidence from the
    # agent's context, which is the opposite of grounding it.
    truncated = len(content) > 20000
    return json.dumps({"ok": True, "repo": repo, "path": path, "truncated": truncated, "content": content[:20000]})


def list_repo_tree(agent, input_str: str) -> str:
    """List file paths in an allowlisted repo. Input: {"repo","ref"?,"prefix"?}."""
    from components.integrations.application.providers.vcs_scan_access_provider import (
        list_repo_tree as _tree,
    )

    data = _parse(input_str)
    repo = (data.get("repo") or "").strip()
    if not repo:
        return json.dumps({"ok": False, "error": "repo is required"})
    paths = _tree(workspace_id=agent.workspace_id, repo=repo, ref=(data.get("ref") or "").strip())
    prefix = (data.get("prefix") or "").strip().lstrip("/")
    if prefix:
        paths = [p for p in paths if p.startswith(prefix)]
    return json.dumps({"ok": True, "repo": repo, "count": len(paths), "paths": paths})


def search_repo(agent, input_str: str) -> str:
    """Search an allowlisted repo's code. Input: {"repo","query","limit"?}."""
    from components.integrations.application.providers.vcs_scan_access_provider import (
        search_repo as _search,
    )

    data = _parse(input_str)
    repo, query = (data.get("repo") or "").strip(), (data.get("query") or "").strip()
    if not repo or not query:
        return json.dumps({"ok": False, "error": "repo and query are required"})
    try:
        limit = max(1, min(int(data.get("limit") or 20), 50))
    except (TypeError, ValueError):
        limit = 20
    hits = _search(workspace_id=agent.workspace_id, repo=repo, query=query, limit=limit)
    # An empty result is a real answer ("this project has no such symbol"), not an
    # error — that distinction is what stops the model inventing one.
    return json.dumps({"ok": True, "repo": repo, "query": query, "count": len(hits), "hits": hits})
