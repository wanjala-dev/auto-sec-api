"""Rule → remediation guidance: what a CORRECT fix looks like (ADR 0019 D5).

THE PROBLEM. A SAST rule message says what is WRONG ("Raw SQL built with
%-formatting"). It does not say what RIGHT looks like. The advisor was given only
that message plus the matched snippet, so it inferred the remediation — and
inference without the domain distinction produces fixes that are grounded,
in-scope, syntactically valid and semantically wrong. The dogfood case (PR #866,
reproduced independently in #869) proposed binding a schema IDENTIFIER as a query
parameter: Postgres renders it as a quoted literal, so the patch trades an
injection risk for a statement that fails on every run.

THE SHAPE. Guidance is keyed by remediation CLASS, not by rule, because the
knowledge clusters by fix shape — three "shell" rules have one answer. Classes
live in ``rules/remediation/classes.yaml``; the rule→class binding lives in
``rules/remediation/bindings.yaml`` with a CWE fallback so an imported pack
inherits guidance without per-rule authoring. See those files for the resolution
contract and why bindings sit outside the license-audited packs.

TWO USES, DELIBERATELY SEPARATE:

* :func:`prompt_block` — what the ADVISOR is told before it writes a fix. Prose,
  a worked example, and the anti-example.
* :func:`check_patch` — what the VERIFIER runs against the fix that came back.
  Deterministic regexes over the PROPOSED code.

The distinction matters more than it looks. The verifier's grounding text for a
SAST suggestion is ``likely_cause + suggested_fix + fix_before`` — it deliberately
includes the OFFENDING line so a fix that quotes it counts as grounded. Running
anti-patterns over that text would match the vulnerability every time (``shell=True``
is in ``fix_before`` by construction) and veto every fix. :func:`check_patch` is
therefore documented and typed to take the PROPOSED patch (``fix_after``) only.

Framework-free: no Django, no ORM. Pure domain knowledge + stdlib.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_REMEDIATION_DIR = Path(__file__).resolve().parents[1] / "rules" / "remediation"
_CLASSES_FILE = _REMEDIATION_DIR / "classes.yaml"
_BINDINGS_FILE = _REMEDIATION_DIR / "bindings.yaml"


class RemediationGuidanceError(RuntimeError):
    """The guidance corpus is missing or malformed — fail loud, never guess."""


@dataclass(frozen=True)
class AntiPattern:
    """A deterministic check for a known-wrong fix shape."""

    regex: str
    why: str

    def matches(self, code: str) -> bool:
        try:
            return re.search(self.regex, code) is not None
        except re.error:  # pragma: no cover - the fitness test compiles every regex
            logger.exception("remediation_guidance bad anti-pattern regex=%r", self.regex)
            return False


@dataclass(frozen=True)
class RemediationGuidance:
    """What a correct fix looks like for one remediation class."""

    remediation_class: str
    recommendation: str
    correct: str
    wrong: str
    why: str
    anti_patterns: tuple[AntiPattern, ...] = ()
    #: How this rule resolved to this class — ``"rule"`` (explicit binding) or
    #: ``"cwe"`` (inherited from the weakness). Carried for logging so an
    #: imported pack's coverage is measurable rather than assumed.
    source: str = "rule"


@dataclass(frozen=True)
class AntiPatternHit:
    """A proposed patch reproduced a known-wrong shape."""

    remediation_class: str
    why: str
    regex: str


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, RemediationGuidance], dict[str, str], dict[str, str], dict[str, str]]:
    """Return ``(classes, rule_bindings, cwe_bindings, unmapped)`` — cached."""
    if not _CLASSES_FILE.is_file():
        raise RemediationGuidanceError(f"Remediation classes missing: {_CLASSES_FILE}")
    if not _BINDINGS_FILE.is_file():
        raise RemediationGuidanceError(f"Remediation bindings missing: {_BINDINGS_FILE}")

    raw_classes = (yaml.safe_load(_CLASSES_FILE.read_text()) or {}).get("classes") or {}
    if not raw_classes:
        raise RemediationGuidanceError("Remediation classes file declares no classes")

    classes: dict[str, RemediationGuidance] = {}
    for name, body in raw_classes.items():
        body = body or {}
        missing = [k for k in ("recommendation", "correct", "wrong", "why") if not str(body.get(k) or "").strip()]
        if missing:
            raise RemediationGuidanceError(f"Remediation class {name!r} is missing: {', '.join(missing)}")
        classes[str(name)] = RemediationGuidance(
            remediation_class=str(name),
            recommendation=str(body["recommendation"]).strip(),
            correct=str(body["correct"]).strip(),
            wrong=str(body["wrong"]).strip(),
            why=str(body["why"]).strip(),
            anti_patterns=tuple(
                AntiPattern(regex=str(ap.get("regex") or ""), why=str(ap.get("why") or ""))
                for ap in (body.get("anti_patterns") or [])
                if str(ap.get("regex") or "").strip()
            ),
        )

    bindings_doc = yaml.safe_load(_BINDINGS_FILE.read_text()) or {}
    rule_bindings = {str(k): str(v) for k, v in (bindings_doc.get("rules") or {}).items()}
    cwe_bindings = {str(k).upper(): str(v) for k, v in (bindings_doc.get("cwe") or {}).items()}
    unmapped = {str(k): str(v) for k, v in (bindings_doc.get("unmapped") or {}).items()}

    for source, mapping in (("rules", rule_bindings), ("cwe", cwe_bindings)):
        for key, class_name in mapping.items():
            if class_name not in classes:
                raise RemediationGuidanceError(
                    f"Binding {source}:{key} points at unknown remediation class {class_name!r}"
                )

    return classes, rule_bindings, cwe_bindings, unmapped


def remediation_classes() -> dict[str, RemediationGuidance]:
    """Every declared class, keyed by name (for the fitness test + diagnostics)."""
    return dict(_load()[0])


def rule_bindings() -> dict[str, str]:
    """Explicit rule-id → class bindings (for the coverage fitness test)."""
    return dict(_load()[1])


def unmapped_rules() -> dict[str, str]:
    """Rules deliberately left without guidance → the recorded reason."""
    return dict(_load()[3])


def guidance_for(rule_id: str, cwes: object = ()) -> RemediationGuidance | None:
    """Resolve a rule's remediation guidance, or ``None`` when nothing applies.

    Order: explicit rule binding, then the rule's CWE metadata, then nothing. A
    miss is degraded behaviour (the advisor works exactly as it did before this
    module existed), never an error — an unmapped rule must still produce a fix.
    """
    classes, rules, cwe_map, _ = _load()
    key = str(rule_id or "").strip()
    if not key:
        return None

    bound = rules.get(key)
    if bound:
        return classes[bound]

    for cwe in _iter_cwes(cwes):
        bound = cwe_map.get(cwe)
        if bound:
            logger.info("remediation_guidance resolved_via_cwe rule_id=%s cwe=%s class=%s", key, cwe, bound)
            return replace(classes[bound], source="cwe")

    logger.info("remediation_guidance unmapped rule_id=%s", key)
    return None


def _iter_cwes(cwes: object):
    """Normalise the many shapes a rule's CWE metadata arrives in.

    Registry rules write ``cwe: ["CWE-89: SQL Injection"]``, ours write
    ``cwe: [CWE-89]``, and some write a bare string. All three must resolve.
    """
    if not cwes:
        return
    values = cwes if isinstance(cwes, (list, tuple, set)) else [cwes]
    for value in values:
        match = re.search(r"CWE[-_ ]?(\d+)", str(value), re.IGNORECASE)
        if match:
            yield f"CWE-{match.group(1)}"


def prompt_block(guidance: RemediationGuidance | None) -> str:
    """The advisor-facing guidance block, or ``""`` when the rule is unmapped.

    Leads with the recommendation, shows the correct shape, then names the
    near-miss explicitly. The anti-example is the load-bearing part: the failures
    this exists to stop were all *plausible*, so telling the model what right looks
    like is not enough — it has to be told which wrong answer it is drawn to.
    """
    if guidance is None:
        return ""
    lines = [
        "remediation guidance for this rule class "
        f"({guidance.remediation_class}) — follow it unless the code contradicts it:",
        f"  how to fix: {guidance.recommendation}",
        "  correct shape:",
        *[f"    {ln}" for ln in guidance.correct.splitlines()],
        "  a WRONG fix that looks right (do not produce this):",
        *[f"    {ln}" for ln in guidance.wrong.splitlines()],
        f"  why the difference matters: {guidance.why}",
        "",
    ]
    return "\n".join(lines)


def check_patch(patch_code: str, guidance: RemediationGuidance | None) -> AntiPatternHit | None:
    """Return the first anti-pattern the PROPOSED patch reproduces, if any.

    ``patch_code`` MUST be the proposed replacement (``fix_after``) — never the
    grounding text, which contains the offending line and would match by
    construction. See this module's docstring.
    """
    if guidance is None:
        return None
    code = str(patch_code or "")
    if not code.strip():
        return None
    for anti in guidance.anti_patterns:
        if anti.matches(code):
            return AntiPatternHit(remediation_class=guidance.remediation_class, why=anti.why, regex=anti.regex)
    return None
