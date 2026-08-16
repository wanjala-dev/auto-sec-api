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

import ast
import logging
import re
import textwrap
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
    #: How this class should be REPAIRED. Measured fix rates vary from 0% to
    #: 45% by weakness type (arXiv 2603.10072), so attempting every class the
    #: same way manufactures noise. ``guidance_only`` means the correct fix
    #: depends on knowledge that lives in the customer's codebase (an issuer's
    #: key source, a serialisation decision) — we hand the operator grounded
    #: instructions instead of a guessed patch, and say so.
    strategy: str
    recommendation: str
    correct: str
    wrong: str
    why: str
    anti_patterns: tuple[AntiPattern, ...] = ()
    #: Fragments of ``correct`` that are stand-ins for something only THIS
    #: codebase can supply. Written so that copying them produces invalid code
    #: — the live failure was an exemplar helper (``fetch_jwks_key``) pasted
    #: verbatim into a real patch, which no anti-pattern catches because the
    #: SHAPE was right and only the symbol was fictional.
    placeholders: tuple[str, ...] = ()
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
        missing = [
            k for k in ("strategy", "recommendation", "correct", "wrong", "why") if not str(body.get(k) or "").strip()
        ]
        if missing:
            raise RemediationGuidanceError(f"Remediation class {name!r} is missing: {', '.join(missing)}")
        classes[str(name)] = RemediationGuidance(
            remediation_class=str(name),
            strategy=str(body["strategy"]).strip(),
            recommendation=str(body["recommendation"]).strip(),
            correct=str(body["correct"]).strip(),
            wrong=str(body["wrong"]).strip(),
            why=str(body["why"]).strip(),
            placeholders=tuple(str(ph) for ph in (body.get("placeholders") or []) if str(ph).strip()),
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

    Ordering is load-bearing and measured, not stylistic. The 2026-08-16
    baseline caught the model returning the block's wrong example BYTE-FOR-BYTE
    as its fix — the anchoring failure the repair literature quantifies (~44%
    of model errors reproduce shown wrong code verbatim). Two rules follow:

    - The wrong example appears only as a LABELED CONTRASTIVE PAIR — the
      near-miss with its why attached, immediately followed by the correct
      shape — never as a free-standing "don't do this" (that is the
      pink-elephant form our own prompt-hygiene rules ban).
    - The CORRECT shape is the LAST code the model reads. Recency wins;
      putting the wrong example last is what the baseline measured.
    """
    if guidance is None:
        return ""
    lines = [
        "remediation guidance for this rule class "
        f"({guidance.remediation_class}) — follow it unless the code contradicts it:",
        f"  how to fix: {guidance.recommendation}",
        "  the near-miss this rule's fixes are drawn to:",
        *[f"    {ln}" for ln in guidance.wrong.splitlines()],
        f"  why it fails: {guidance.why}",
        "  the correct SHAPE to produce instead (an illustration, NOT code to copy):",
        *[f"    {ln}" for ln in guidance.correct.splitlines()],
    ]
    if guidance.placeholders:
        lines.append(
            "  the example contains PLACEHOLDERS you must replace with the real "
            f"symbols from this file: {', '.join(guidance.placeholders)}"
        )
    # Restated HERE, last, on purpose. The system prompt already forbids inventing
    # APIs and already asks for the rule + file by name — and the first live run
    # violated both the moment this block was added, because a concrete worked
    # example out-competes a general instruction the model read earlier. The
    # specific guidance has to carry the general constraints with it.
    lines += [
        "  use the identifiers that exist in THIS file — never copy a name from the "
        "example; it is illustrative and its symbols may not exist here",
        "  name the rule and the flagged file in suggested_fix, as required above",
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


# ── Repair strategies (research-driven routing) ──────────────────────────────
#
# Measured LLM security-patch correctness is 24.8% overall, and 0%–45% depending
# on the weakness (arXiv 2603.10072). The same paper's other finding is that the
# outcome distribution is BIMODAL — only 0.3% of patches land near-correct — so
# better prompting cannot close the gap; the answer is to attempt the classes a
# model can actually do, and hand the rest to the operator as grounded guidance.

#: The model may propose a patch; the oracles below decide whether it ships.
STRATEGY_LLM = "llm_plus_oracles"
#: No patch is attempted. The correct fix depends on knowledge that only exists
#: in the customer's codebase, so a generated one is a guess wearing a fix's
#: clothes. The operator gets the recommendation, named as guidance.
STRATEGY_GUIDANCE_ONLY = "guidance_only"

VALID_STRATEGIES = frozenset({STRATEGY_LLM, STRATEGY_GUIDANCE_ONLY})


def patch_is_attempted(guidance: RemediationGuidance | None) -> bool:
    """Should a PATCH be generated for this class at all?

    Unmapped rules keep today's behaviour (attempt it) — a rule we have not
    classified must not silently lose its artifact.
    """
    if guidance is None:
        return True
    return guidance.strategy != STRATEGY_GUIDANCE_ONLY


@dataclass(frozen=True)
class SyntaxVerdict:
    """Result of the L1 syntactic oracle.

    ``ok`` and ``checked`` are DIFFERENT questions, and conflating them is what
    this class was corrected for (2026-08-13). "The patch parses" and "we have no
    parser for this language, so nobody looked" both used to return ``ok=True``,
    which made an unexamined patch indistinguishable from a validated one.

    Everything else shipped this session distinguishes the two — ``priced=False``
    for an unpriceable run, ``verification="unverified"`` for an ungrounded fix,
    a missing attestation for an ungraded patch. This oracle was the one place
    still answering "fine" when it meant "unknown".
    """

    ok: bool
    reason: str = ""
    #: False when no parser was available for the language, i.e. the verdict is
    #: an ABSTENTION rather than a pass. Callers must not treat this as
    #: validation; surface it the way an unpriced cost or an unverified fix is
    #: surfaced. Defaults True so existing constructions keep meaning "checked".
    checked: bool = True


def patch_parses(*, patch_code: str, before_code: str, language: str) -> SyntaxVerdict:
    """L1 oracle: did the model return code that still parses?

    13.2% of LLM security patches simply do not compile (arXiv 2603.10072), and a
    broken patch is the cheapest possible thing to catch — no model, no network.

    The subtlety is that a patch is a FRAGMENT, not a file: an indented body line
    fails to parse on its own for reasons that have nothing to do with the fix. So
    the verdict is COMPARATIVE — we only fail the patch when the ``before``
    fragment parses and the ``after`` fragment does not, i.e. when the model
    demonstrably broke something that was fine. When neither parses we cannot tell
    fragment context from real breakage, and we pass: an oracle that cries wolf
    gets muted, and muting this one costs more than it saves.

    Python only for now, deliberately: it is the only language whose parser ships
    in this image. Claiming coverage we do not have would be worse than the gap.
    """
    lang = str(language or "").strip().lower()
    if lang not in {"python", "py"}:
        # ABSTAIN, do not pass. No parser for this language ships in the image,
        # so we have not examined this patch — say so rather than returning a
        # verdict that reads identically to a real pass. The patch still flows
        # (withholding the artifact was never the policy); it simply must not
        # claim a syntax check it never had.
        return SyntaxVerdict(
            ok=True,
            checked=False,
            reason=f"no {lang or 'unknown-language'} parser available — patch syntax NOT checked",
        )
    after = textwrap.dedent(str(patch_code or ""))
    before = textwrap.dedent(str(before_code or ""))
    if not after.strip():
        return SyntaxVerdict(ok=True)  # emptiness is handled by the caller, not here
    if _parses(after):
        return SyntaxVerdict(ok=True)
    if not _parses(before):
        # The before-fragment does not parse standalone either → this is fragment
        # context, not a broken patch. Inconclusive, so pass.
        return SyntaxVerdict(ok=True)
    return SyntaxVerdict(
        ok=False,
        reason=(
            "The proposed patch is not valid Python, while the code it replaces is — "
            "the fix introduces a syntax error. Return a patch that parses."
        ),
    )


def _parses(fragment: str) -> bool:
    try:
        ast.parse(fragment)
    except SyntaxError:
        return False
    except (ValueError, MemoryError, RecursionError):
        # Pathological input — inconclusive rather than "broken".
        return True
    return True
