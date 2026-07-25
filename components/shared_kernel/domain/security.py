"""Shared security value objects — the cross-pillar vocabulary of a CNAPP.

These are the canonical, OCSF-aligned types every scanning pillar and every lens
speaks, so a Prowler misconfiguration, a Trivy CVE, and a CIEM entitlement gap all
carry *comparable* severity/status/identity. They live in the shared kernel because
they are the minimal contract shared across bounded contexts (ADR 0004 D5/C6) — no
component owns them, so no component couples to another by using them.

Design notes:
- Vendor-neutral. Converters accept the OCSF canonical form (``from_ocsf_id``);
  vendor-specific mapping (Prowler/Trivy → OCSF) belongs in each scanner's adapter,
  never here — that keeps the kernel from mimicking any one tool's API.
- Aggregate-light. These are lean immutable value objects, not aggregate roots.
- Events carry the *primitive* form of these (``Severity.value`` etc.), because the
  Celery event bus serialises by field annotation; the rich types are used inside a
  context's domain, the strings travel on the wire. See ``domain/events.py``.

Reference: https://schema.ocsf.io/classes/security_finding
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import total_ordering

__all__ = ["AssetUrn", "FindingStatus", "RiskBand", "Severity"]


@total_ordering
class Severity(Enum):
    """Canonical finding severity, orderable worst-last (``max(...)`` = worst).

    ``INFORMATIONAL < LOW < MEDIUM < HIGH < CRITICAL``. Use ``.rank`` for a numeric
    key, or compare directly (``sev >= Severity.HIGH``).
    """

    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank

    @classmethod
    def from_name(cls, name: str) -> Severity:
        """Parse a severity name (canonical values + common aliases).

        Strict on genuinely unknown input — a typo in our own code should fail
        fast rather than silently downgrade a finding. Vendor strings that are not
        obvious aliases should be mapped in the vendor adapter, not here.
        """
        key = (name or "").strip().lower()
        try:
            return cls(key)
        except ValueError:
            pass
        alias = _SEVERITY_ALIASES.get(key)
        if alias is not None:
            return alias
        raise ValueError(f"Unknown severity name: {name!r}")

    @classmethod
    def from_ocsf_id(cls, severity_id: int) -> Severity:
        """Map an OCSF ``severity_id`` to a canonical Severity.

        OCSF: 0 Unknown · 1 Informational · 2 Low · 3 Medium · 4 High · 5 Critical
        · 6 Fatal · 99 Other. Unknown/Other resolve to ``INFORMATIONAL`` — we do not
        manufacture urgency from an absence of signal.
        """
        return _OCSF_SEVERITY.get(int(severity_id), cls.INFORMATIONAL)


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFORMATIONAL: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}

_SEVERITY_ALIASES: dict[str, Severity] = {
    "info": Severity.INFORMATIONAL,
    "informational": Severity.INFORMATIONAL,
    "moderate": Severity.MEDIUM,
    "med": Severity.MEDIUM,
    "crit": Severity.CRITICAL,
}

_OCSF_SEVERITY: dict[int, Severity] = {
    1: Severity.INFORMATIONAL,
    2: Severity.LOW,
    3: Severity.MEDIUM,
    4: Severity.HIGH,
    5: Severity.CRITICAL,
    6: Severity.CRITICAL,  # OCSF "Fatal" maps to our top band
}


class FindingStatus(Enum):
    """Lifecycle state of a finding in the ``findings`` SSOT (ADR 0004 D1).

    ``OPEN`` and ``TRIAGED`` are actionable; ``RESOLVED`` and ``SUPPRESSED`` are
    terminal. A re-observed finding that was terminal reopens to ``OPEN``.
    """

    OPEN = "open"  # OCSF: New
    TRIAGED = "triaged"  # OCSF: In Progress
    SUPPRESSED = "suppressed"  # OCSF: Suppressed (accepted risk / false positive)
    RESOLVED = "resolved"  # OCSF: Resolved (remediated / no longer observed)

    @property
    def is_terminal(self) -> bool:
        return self in (FindingStatus.RESOLVED, FindingStatus.SUPPRESSED)

    @classmethod
    def from_ocsf_id(cls, status_id: int) -> FindingStatus:
        """Map an OCSF ``status_id`` (1 New · 2 In Progress · 3 Suppressed ·
        4 Resolved). Unknown resolves to ``OPEN`` — an unknown finding is treated
        as actionable, not silently closed.
        """
        return _OCSF_STATUS.get(int(status_id), cls.OPEN)


_OCSF_STATUS: dict[int, FindingStatus] = {
    1: FindingStatus.OPEN,
    2: FindingStatus.TRIAGED,
    3: FindingStatus.SUPPRESSED,
    4: FindingStatus.RESOLVED,
}


class RiskBand(Enum):
    """Coarse contextual-risk band (green/amber/red) shared with the sign-off spine.

    The numeric contextual-risk score (0–100) is computed by the Phase-6 background
    job (ADR 0004 §6); ``from_score`` gives the provisional banding until that lands.
    """

    GREEN = "green"
    AMBER = "amber"
    RED = "red"

    @classmethod
    def from_score(cls, score: float) -> RiskBand:
        """Band a 0–100 contextual-risk score. Thresholds are provisional and will
        be tuned when the Phase-6 scorer ships; keep them in one place here so the
        tuning is a single edit.
        """
        value = max(0.0, min(100.0, float(score)))
        if value >= 67.0:
            return cls.RED
        if value >= 34.0:
            return cls.AMBER
        return cls.GREEN


@dataclass(frozen=True)
class AssetUrn:
    """Canonical, cross-pillar identity for a cloud asset.

    This is the **correlation key** that links a finding (owned by the ``findings``
    context) to a node in the security graph (owned by the generalized ``provenance``
    context) — carried by *value*, never a cross-component foreign key (ADR 0004 D4).
    A finding and an entitlement edge that name the same ``AssetUrn`` are, by
    definition, about the same asset; that identity is what makes attack-path
    correlation a graph query rather than a string match.
    """

    value: str

    def __post_init__(self) -> None:
        cleaned = (self.value or "").strip()
        if not cleaned:
            raise ValueError("AssetUrn value cannot be empty")
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value

    @property
    def provider(self) -> str:
        """Best-effort cloud provider from the identity scheme.

        ``arn:aws:...`` → ``aws``; ``urn:<provider>:...`` → ``<provider>``; anything
        else → ``unknown``. Kept intentionally shallow — deep ARN parsing belongs to
        whichever adapter needs it, not to this shared value object.
        """
        parts = self.value.split(":")
        if len(parts) >= 2 and parts[0] in ("arn", "urn"):
            return parts[1].lower()
        return "unknown"

    @classmethod
    def from_aws_arn(cls, arn: str) -> AssetUrn:
        cleaned = (arn or "").strip()
        if not cleaned.startswith("arn:aws:"):
            raise ValueError(f"Not an AWS ARN: {arn!r}")
        return cls(cleaned)
