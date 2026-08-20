"""Contract: exactly ONE confidence statistic exists in this codebase.

ADR 0032 D3. The Wilson lower bound, the tier ladder and the three display
states live in ``components/shared_kernel/domain/measured_rate.py`` and
nowhere else. Every surface that turns a fraction into a trust claim —
per-SAST-rule fix confidence, agent/model measurement, any future panel —
consumes that module.

The failure this prevents is specific and it has a shape: someone needs a
confidence number for a new surface, finds ``fix_confidence.py`` is bound to
a SAST rule corpus, and writes a second Wilson. The two then drift — one
gets a fix, a floor change, an expiry rule the other misses — and the
product shows two different confidence numbers for the same fact. That is
the defect ``dry-reuse.md`` §4 ("one canonical thing per concern") names,
and prose did not stop it the last three times, so it is asserted here.

A grep, deliberately: an import-graph check would miss a hand-rolled copy
that imports nothing, which is exactly the copy we are worried about.
"""

from __future__ import annotations

import re
from pathlib import Path

# tests/architecture/<this file> -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The single owner.
_CANONICAL = _REPO_ROOT / "components" / "shared_kernel" / "domain" / "measured_rate.py"

#: Trees that ship product code. Tests may assert on the maths (they pin the
#: calibration points); they may not re-implement it, so they are scanned too
#: for a *definition*, just not for use of the constant.
_SCANNED = ("components", "infrastructure", "api")

#: The Wilson centre/margin algebra. Any file computing this itself — rather
#: than calling the shared kernel — is a second implementation.
_WILSON_DEF = re.compile(r"def\s+wilson_(lower|upper)_bound\s*\(")

#: The one-sided 95% z-quantile as a literal. Recomputing it in a second
#: place is how two "95%" bounds end up not being the same 95%.
_Z_LITERAL = re.compile(r"1\.6448536269514722")


def _python_files():
    for tree in _SCANNED:
        for path in (_REPO_ROOT / tree).rglob("*.py"):
            if path == _CANONICAL:
                continue
            if "/migrations/" in str(path):
                continue
            yield path


def test_only_the_shared_kernel_defines_the_wilson_bound():
    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in _python_files()
        if _WILSON_DEF.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not offenders, (
        "A second Wilson bound was defined outside the shared kernel:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nFix: import it from components.shared_kernel.domain.measured_rate. "
        "Two implementations of one statistic drift, and the product then shows "
        "two different confidence numbers for the same fact (ADR 0032 D3)."
    )


def test_only_the_shared_kernel_hardcodes_the_z_quantile():
    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in _python_files()
        if _Z_LITERAL.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not offenders, (
        "The one-sided 95% z-quantile is hardcoded outside the shared kernel:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nFix: import Z_ONE_SIDED_95 from "
        "components.shared_kernel.domain.measured_rate."
    )


def test_the_canonical_module_is_framework_free():
    """A shared-kernel statistic that imports Django is not reusable.

    ``fix_confidence`` is a domain module with no Django in it; the agents
    context reads this from a Celery task and a DRF resource. The moment the
    statistic imports a framework it stops being liftable into either.
    """
    source = _CANONICAL.read_text(encoding="utf-8")
    for banned in ("import django", "from django", "import rest_framework", "from rest_framework"):
        assert banned not in source, f"{_CANONICAL.name} imports a framework ({banned!r})"
