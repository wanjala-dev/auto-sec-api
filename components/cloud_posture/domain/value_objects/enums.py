"""Framework-free cloud-posture enums (mirror the ORM TextChoices)."""

from __future__ import annotations

from enum import StrEnum

# Prowler severity ordering — higher = worse. Used to map to a board impact score
# and to rank findings without string comparisons.
_SEVERITY_ORDER = {
    "informational": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "critical": 5,
}


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"

    @property
    def order(self) -> int:
        return _SEVERITY_ORDER[self.value]


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    MANUAL = "manual"


def severity_from_prowler(raw: str | None) -> Severity:
    """Map a Prowler severity string (any case) to a Severity; default MEDIUM."""
    value = (raw or "").strip().lower()
    try:
        return Severity(value)
    except ValueError:
        return Severity.MEDIUM


def status_from_prowler(raw: str | None) -> CheckStatus:
    """Map a Prowler ``status_code`` (PASS/FAIL/MANUAL) to a CheckStatus."""
    value = (raw or "").strip().lower()
    if value == "pass":
        return CheckStatus.PASS
    if value == "fail":
        return CheckStatus.FAIL
    return CheckStatus.MANUAL
