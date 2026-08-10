"""``AgentUrn`` — the decided identity namespace for a CUSTOMER's AI agent (ADR 0023 D1).

    ``urn:agent:<platform>:<external_ref>``

Registered here, never defaulted. ADR 0021 D1's trap applies verbatim: a wrongly
namespaced identity "would not fail loudly; it would succeed and lie" — two agents
on two platforms sharing an opaque id would silently become one actor, and every
attribution statement built on that actor would be false.

This is the sibling of :class:`components.shared_kernel.domain.security.AssetUrn`:
``AssetUrn`` names a *thing acted upon*, ``AgentUrn`` names an *actor*. They are
deliberately separate namespaces so a graph query can never confuse the two.

⚠ **Attribution is a join WE perform, never a field we read.** No telemetry standard
carries a principal, subject, or credential attribute (ADR 0023 D2 / R1), and
Stripe — verified via the Stripe MCP, 2026-08-09 — does **not** expose the acting
API key per request programmatically: its request logs are a Dashboard/Workbench
surface, and the v2 Activity Logs API covers key *lifecycle*, not key *usage*. So
the ``external_ref`` below is whatever the customer's own runtime self-reported.
It is an *asserted* identity, not a verified one. Nothing downstream may treat it
as proof of who acted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NAMESPACE = "urn:agent"

# Conservative: the URN is a stored identity and a log field, so keep it to
# characters that cannot smuggle a delimiter, whitespace, or control byte.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._~@/+-]+$")

# ProvenanceActor.external_ref is CharField(255); refuse rather than silently
# truncate, because a truncated identity is a WRONG identity.
MAX_URN_LENGTH = 255


@dataclass(frozen=True)
class AgentUrn:
    """A customer agent's stable, platform-namespaced identity."""

    value: str

    def __post_init__(self) -> None:
        cleaned = (self.value or "").strip()
        if not cleaned.startswith(f"{NAMESPACE}:"):
            raise ValueError(f"AgentUrn must start with {NAMESPACE}: — got {cleaned!r}")
        if len(cleaned) > MAX_URN_LENGTH:
            raise ValueError(f"AgentUrn exceeds {MAX_URN_LENGTH} chars: {cleaned[:40]!r}…")
        object.__setattr__(self, "value", cleaned)

    def __str__(self) -> str:
        return self.value

    @property
    def platform(self) -> str:
        parts = self.value.split(":", 3)
        return parts[2] if len(parts) >= 3 else ""

    @property
    def external_ref(self) -> str:
        parts = self.value.split(":", 3)
        return parts[3] if len(parts) >= 4 else ""

    @classmethod
    def build(cls, platform: str, external_ref: str) -> AgentUrn:
        """The ONE place a customer-agent identity is constructed.

        Both segments are normalized (lowercased platform, stripped ref) and
        validated against :data:`_SAFE_SEGMENT`. A ref we cannot represent
        losslessly raises — we never coerce it into something that would resolve
        to a different agent.
        """
        plat = (platform or "").strip().lower()
        ref = (external_ref or "").strip()
        if not plat or not _SAFE_SEGMENT.match(plat):
            raise ValueError(f"Unusable agent platform: {platform!r}")
        if not ref or not _SAFE_SEGMENT.match(ref):
            raise ValueError(f"Unusable agent external_ref: {external_ref!r}")
        return cls(f"{NAMESPACE}:{plat}:{ref}")
