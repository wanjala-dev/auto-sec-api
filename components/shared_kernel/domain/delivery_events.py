"""The external delivery event catalog — the shared vocabulary of "what can be sent out".

Two contexts need these keys and neither owns them:

* **notifications** classifies each dispatch into an ``event_key`` and decides whether
  the external leg fires (ADR 0016 D4).
* **integrations** validates a connection's subscription list against the catalog and
  stores it on the row.

ADR 0016 D4 sketches this living in ``components/notifications/domain``. It is placed
in the shared kernel instead, because notifications must import integrations' delivery
provider (D1) — putting the vocabulary in notifications too would make the two contexts
depend on each other in both directions, which is precisely the coupling C1 says the
kernel exists to absorb. Same reasoning as ``FindingRaised`` living here rather than in
``findings``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalEvent:
    """One deliverable event class."""

    key: str
    label: str
    description: str
    default_on: bool = True


DRAFT_PR_OPENED = "draft_pr_opened"
FINDING_CRITICAL = "finding_critical"
SCAN_FAILED = "scan_failed"
SCAN_DIGEST = "scan_digest"
RISK_ACCEPT_EXPIRING = "risk_accept_expiring"


EXTERNAL_EVENT_CATALOG: tuple[ExternalEvent, ...] = (
    ExternalEvent(
        key=DRAFT_PR_OPENED,
        label="AI opened a draft PR",
        description="An agent proposed a fix and opened a draft pull request for review.",
    ),
    ExternalEvent(
        key=FINDING_CRITICAL,
        label="Critical finding",
        description=(
            "A newly observed critical finding. A known-exploited (KEV) finding qualifies "
            "regardless of the channel's severity floor."
        ),
    ),
    ExternalEvent(
        key=SCAN_FAILED,
        label="Scan failed",
        description="A scan engine failed loud — coverage is silently degraded until it is fixed.",
    ),
    ExternalEvent(
        key=SCAN_DIGEST,
        label="Scan summary",
        description="One message per completed scan with counts by severity — never one message per finding.",
    ),
    ExternalEvent(
        key=RISK_ACCEPT_EXPIRING,
        label="Risk acceptance expiring",
        description="An accepted risk is about to lapse and the finding will reopen.",
        # Reserved by ADR 0016 D4; the emitter is ADR 0015 P2 and is not built yet, so a
        # connection subscribing to it today simply never receives one.
        default_on=False,
    ),
)


EXTERNAL_EVENT_KEYS: frozenset[str] = frozenset(event.key for event in EXTERNAL_EVENT_CATALOG)

DEFAULT_EXTERNAL_EVENT_KEYS: tuple[str, ...] = tuple(
    event.key for event in EXTERNAL_EVENT_CATALOG if event.default_on
)


def is_known_event_key(key: str) -> bool:
    return (key or "").strip().lower() in EXTERNAL_EVENT_KEYS
