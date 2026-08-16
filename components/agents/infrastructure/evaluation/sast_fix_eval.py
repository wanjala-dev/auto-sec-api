"""SAST fix-quality eval harness — measure the advisor before touching it (#117).

ADR 0025's corpus was a five-row markdown table; every intervention since has
been argued from three live cards. This harness makes the measurement runnable
and CLASS-STRATIFIED, because the aggregate number conflates two different
problems (task #117): Class A findings a bounded edit can fix, and Class B
findings that need a design change, where the honest output is a decline.

The harness drives the REAL production choreography, not a simplification —
the advise → verify → one-re-advise-with-reason → re-verify loop is copied
from ``_finding_processing.process_pending_finding`` (its lines 237–267), with
the fixture supplying the file content the advisor grounds on. What differs
from production is only what must differ for a lab: the repo file comes from a
frozen fixture instead of the VCS seam, and the Remediation-Memory grounding
block is empty (no workspace).

Gate pipeline per candidate fix, cheapest first, recording WHICH gate failed
(the per-gate failure counts are the iteration signal — GitHub tripled its
autofix success rate by iterating against harness failures, not aggregate
accuracy):

    artifact   — is there a patch at all (guidance_only classes exempt)
    parse      — does the replacement still parse (comparative; abstains
                 where the fragment or language is uncheckable)
    shape      — does it reproduce a known-wrong shape for its remediation
                 class (the L3 oracle)
    anti_gaming— deletion-only, suppression markers, dead-coding: shapes that
                 make a finding disappear without fixing anything
    rescan     — SKIPPED, recorded as such: the L2 oracle needs the opengrep
                 binary in the app image (ADR 0025). A skipped gate printed in
                 the report is honest; a silently absent one reads as covered.

Metrics are COUNTS per rule and per remediation class ("4/5"), never
percentages: at n≤10 per rule a percentage laundering three easy fixtures into
"75%" is exactly the aggregate-accuracy trap the corpus split exists to avoid.

Fixtures are FROZEN: the corpus is versioned under
``components/agents/tests/sast_fix_eval/fixtures/`` and template/guidance work
must never tune against it in the same change that edits it — zero overlap
between what the author tuned on and what the harness scores.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path

from components.code_security.domain.remediation_guidance import (
    STRATEGY_GUIDANCE_ONLY,
    check_patch,
    guidance_for,
    patch_parses,
)

logger = logging.getLogger(__name__)

#: Matches the production snippet shape: the matched region ± 3 context lines
#: (ADR 0019 D8), so the verifier sees what it would see on a live finding.
SNIPPET_CONTEXT_LINES = 3

#: Suppression markers that make a scanner shut up without fixing anything.
#: A patch containing one "passes" a naive did-the-finding-disappear oracle —
#: the research calls this the most common way autofix metrics get gamed.
_SUPPRESSION_MARKERS = (
    "# nosec",
    "# noqa",
    "nosemgrep",
    "semgrep-ignore",
    "opengrep-ignore",
    "eslint-disable",
)

_DEAD_CODE_GUARDS = (
    re.compile(r"^\s*if\s+(False|0)\s*:", re.MULTILINE),
    re.compile(r"^\s*return\b.*#.*(skip|disable)", re.IGNORECASE | re.MULTILINE),
)


@dataclass(frozen=True)
class FixEvalFixture:
    """One frozen finding: the scanner facts plus the file content they hit."""

    id: str
    rule_id: str
    fix_class: str  # "A" (patchable by a local edit) | "B" (needs a design change)
    kind: str  # stratum within the remediation class, e.g. "sql-identifier"
    path: str
    start_line: int
    end_line: int
    language: str
    message: str
    source_content: str
    expected: str  # "patch" | "decline"
    notes: str = ""
    awkward: bool = False

    @property
    def snippet(self) -> str:
        lines = self.source_content.splitlines()
        lo = max(0, self.start_line - 1 - SNIPPET_CONTEXT_LINES)
        hi = min(len(lines), self.end_line + SNIPPET_CONTEXT_LINES)
        return "\n".join(lines[lo:hi])

    @property
    def matched_region(self) -> str:
        lines = self.source_content.splitlines()
        return "\n".join(lines[self.start_line - 1 : self.end_line])


@dataclass
class FixtureResult:
    fixture: FixEvalFixture
    suggestion: dict | None = None
    verification: str = ""  # verified | unverified | no_artifact
    verify_reason: str = ""
    readvised: bool = False
    gates: dict = field(default_factory=dict)  # gate -> "pass" | "fail: ..." | "abstained" | "skipped: ..."
    outcome: str = ""  # machine_pass | gated | no_artifact | honest_decline | fabricated_patch

    def as_dict(self) -> dict:
        return {
            "fixture": self.fixture.id,
            "rule_id": self.fixture.rule_id,
            "fix_class": self.fixture.fix_class,
            "kind": self.fixture.kind,
            "awkward": self.fixture.awkward,
            "expected": self.fixture.expected,
            "outcome": self.outcome,
            "verification": self.verification,
            "verify_reason": self.verify_reason,
            "readvised": self.readvised,
            "gates": self.gates,
            "suggestion": self.suggestion,
            # Hand-labeling column — the machine gates catch wrong SHAPES, not
            # every wrong MEANING. A human fills this in on the JSON report:
            # correct | plausible_but_wrong | wrong | (empty = unreviewed).
            "human_verdict": "",
        }


def load_fixtures(fixtures_dir: Path) -> list[FixEvalFixture]:
    """Load every ``*.json`` fixture and its sibling source file."""
    fixtures = []
    for meta_path in sorted(fixtures_dir.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        source = (fixtures_dir / meta["source_file"]).read_text()
        fixtures.append(
            FixEvalFixture(
                id=meta["id"],
                rule_id=meta["rule_id"],
                fix_class=meta["fix_class"],
                kind=meta.get("kind", ""),
                path=meta["path"],
                start_line=int(meta["start_line"]),
                end_line=int(meta["end_line"]),
                language=meta.get("language", "python"),
                message=meta.get("message", ""),
                source_content=source,
                expected=meta["expected"],
                notes=meta.get("notes", ""),
                awkward=bool(meta.get("awkward", False)),
            )
        )
    return fixtures


def run_fixture(fixture: FixEvalFixture, advisor) -> FixtureResult:
    """Drive one fixture through the production advise→verify choreography."""
    from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import (
        verify_suggestion,
    )
    from components.shared_kernel.domain.triage import SOURCE_CODE_SECURITY

    result = FixtureResult(fixture=fixture)
    payload = {
        "rule_id": fixture.rule_id,
        "path": fixture.path,
        "snippet": fixture.snippet,
        "language": fixture.language,
    }

    def advise(feedback: str = ""):
        return advisor.suggest(
            rule_id=fixture.rule_id,
            path=fixture.path,
            start_line=fixture.start_line,
            end_line=fixture.end_line,
            snippet=fixture.snippet,
            message=fixture.message,
            repo="eval/frozen-corpus",
            commit_sha="eval",
            workspace_id="",
            feedback=feedback,
        )

    def verify(s):
        return verify_suggestion(
            source_type=SOURCE_CODE_SECURITY,
            payload=payload,
            suggestion_text=f"{s.likely_cause}\n{s.suggested_fix}",
            patch_code=s.fix_after,
        )

    # ── the production loop, verbatim shape (_finding_processing.py:237-267) ──
    suggestion = advise()
    if suggestion is None:
        result.verification = "no_artifact"
        result.outcome = "no_artifact"
        return result

    vr = verify(suggestion)
    if not vr.grounded:
        retry = advise(feedback=vr.reason)
        result.readvised = True
        if retry is not None:
            suggestion = retry
            vr = verify(retry)
    result.suggestion = suggestion.as_dict()
    result.verification = "verified" if vr.grounded else "unverified"
    result.verify_reason = "" if vr.grounded else vr.reason

    # ── the gate pipeline, cheapest first, each recorded ──────────────────
    guidance = guidance_for(fixture.rule_id)
    guidance_only = guidance is not None and guidance.strategy == STRATEGY_GUIDANCE_ONLY
    patch = suggestion.fix_after or ""

    if guidance_only or not patch.strip():
        result.gates["artifact"] = "pass" if guidance_only else "fail: no patch produced"
    else:
        result.gates["artifact"] = "pass"

    if patch.strip():
        syntax = patch_parses(patch_code=patch, before_code=fixture.snippet, language=fixture.language)
        if not syntax.checked:
            result.gates["parse"] = "abstained"
        else:
            result.gates["parse"] = "pass" if syntax.ok else f"fail: {syntax.reason}"

        hit = check_patch(patch, guidance)
        result.gates["shape"] = "pass" if hit is None else f"fail: {hit.remediation_class} — {hit.why}"

        result.gates["anti_gaming"] = _anti_gaming_gate(patch, fixture)

    result.gates["rescan"] = "skipped: L2 oracle not built (needs opengrep in the app image, ADR 0025)"

    result.outcome = _classify(result, patch=patch)
    return result


def _anti_gaming_gate(patch: str, fixture: FixEvalFixture) -> str:
    """Shapes that make the finding disappear without fixing anything."""
    lowered = patch.lower()
    for marker in _SUPPRESSION_MARKERS:
        if marker in lowered:
            return f"fail: suppression marker '{marker}' — silences the rule instead of fixing the code"
    for guard in _DEAD_CODE_GUARDS:
        if guard.search(patch):
            return "fail: dead-codes the flagged region instead of fixing it"
    # Deletion-only: the "fix" removes the flagged code and replaces it with
    # nothing of substance. Deleting a needed statement passes every syntax
    # check and fails at runtime.
    stripped = [ln for ln in patch.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not stripped:
        return "fail: deletion-only — the flagged code is removed, not fixed"
    return "pass"


def _classify(result: FixtureResult, *, patch: str) -> str:
    fixture = result.fixture
    if fixture.expected == "decline":
        # Class B: the honest output is prose + no fabricated patch. A concrete
        # patch on a finding that needs a design change is the #326 failure
        # (an invented helper), not a success — and doubly so on a
        # guidance_only class, whose whole strategy decision is "we do not
        # patch this".
        if patch.strip():
            return "fabricated_patch"
        return "honest_decline" if result.suggestion else "no_artifact"

    hard_gates = [g for g in ("artifact", "parse", "shape", "anti_gaming") if g in result.gates]
    failed = [g for g in hard_gates if str(result.gates[g]).startswith("fail")]
    if failed or result.verification != "verified":
        return "gated"
    return "machine_pass"


# ── reporting ──────────────────────────────────────────────────────────────


def summarize(results: list[FixtureResult]) -> dict:
    """Per-rule and per-class COUNTS. The aggregate appears last and labeled."""

    def bucket(key_fn):
        out: dict[str, dict] = {}
        for r in results:
            key = key_fn(r)
            slot = out.setdefault(key, {"total": 0, "machine_pass": 0, "honest_decline": 0, "gate_failures": {}})
            slot["total"] += 1
            if r.outcome in ("machine_pass", "honest_decline"):
                slot[r.outcome] += 1
            for gate, verdict in r.gates.items():
                if str(verdict).startswith("fail"):
                    slot["gate_failures"][gate] = slot["gate_failures"].get(gate, 0) + 1
        return out

    class_a = [r for r in results if r.fixture.fix_class == "A"]
    class_b = [r for r in results if r.fixture.fix_class == "B"]
    return {
        "per_rule": bucket(lambda r: r.fixture.rule_id),
        "per_kind": bucket(lambda r: f"{r.fixture.rule_id}::{r.fixture.kind}" if r.fixture.kind else r.fixture.rule_id),
        "class_a": {
            "machine_pass": sum(1 for r in class_a if r.outcome == "machine_pass"),
            "total": len(class_a),
        },
        "class_b": {
            "honest_decline": sum(1 for r in class_b if r.outcome == "honest_decline"),
            "total": len(class_b),
        },
        "aggregate_secondary": {
            "note": "aggregate is reported LAST and never used for a ship decision — per-rule counts decide",
            "machine_pass_or_honest": sum(1 for r in results if r.outcome in ("machine_pass", "honest_decline")),
            "total": len(results),
        },
    }


def write_report(results: list[FixtureResult], *, label: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    payload = {
        "label": label,
        "generated_at": stamp,
        "summary": summarize(results),
        "results": [r.as_dict() for r in results],
    }
    path = out_dir / f"sast-fix-{label}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path
