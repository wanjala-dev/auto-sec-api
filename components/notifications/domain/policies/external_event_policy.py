"""Classify a dispatch into an external event key (ADR 0016 D4).

Pure policy — no framework, no IO. Answers two questions the external leg needs:
*is this dispatch worth sending outside the tenant, and under which subscription
key?* and *what identity makes it the same event on a retry?*

**Fail closed.** An unrecognised dispatch classifies to ``None`` and never leaves
the tenant. That is deliberate: a new internal notification type must be added
here consciously before it can reach a third-party chat service, rather than
leaking the moment someone adds a dispatch call.
"""

from __future__ import annotations

import hashlib

from components.shared_kernel.domain.delivery_events import (
    DRAFT_PR_OPENED,
    FINDING_CRITICAL,
    RISK_ACCEPT_EXPIRING,
    SCAN_DIGEST,
    SCAN_FAILED,
)

# ``metadata["kind"]`` is the discriminator the SOC dispatchers already stamp
# (soc_notification_signal_bridge, open_draft_pr_use_case). Mapping on it rather
# than on notification_type keeps the classification explicit — ``ai_event``
# alone covers findings, draft PRs, kill-switch flips and sign-off escalations.
_KIND_TO_EVENT: dict[str, str] = {
    "soc.draft_pr_opened": DRAFT_PR_OPENED,
    "soc.finding_filed": FINDING_CRITICAL,
    "soc.scan_failed": SCAN_FAILED,
    "soc.scan_completed": SCAN_DIGEST,
    "soc.risk_accept_expiring": RISK_ACCEPT_EXPIRING,
}

# Kinds that are deliberately internal-only. Listed explicitly (rather than
# falling through the default) so the intent is visible and a reviewer can see
# the decision was made rather than forgotten.
_INTERNAL_ONLY_KINDS = frozenset(
    {
        "soc.ai_kill_switch",  # an operator break-glass flip — in-app + email is the audience
        "soc.sign_off_pending",  # routes to a named approver, not a team channel
    }
)

# Metadata keys that identify the *thing* an event is about, most specific first.
# Used to derive a dedup key stable across retries of the same logical event.
_IDENTITY_KEYS = ("finding_id", "scan_id", "run_id", "task_id", "connection_id")


def classify_event(notification_type: str, metadata: dict | None) -> str | None:
    """Return the external event key for a dispatch, or None to keep it internal."""
    kind = str((metadata or {}).get("kind") or "").strip().lower()
    if not kind or kind in _INTERNAL_ONLY_KINDS:
        return None
    return _KIND_TO_EVENT.get(kind)


def derive_dedup_key(*, workspace_id: str, event_key: str, metadata: dict | None) -> str:
    """A stable identity for one logical event.

    The ledger's unique constraint is ``(connection, dedup_key)``, so this is what
    makes a redelivered Celery task converge instead of double-posting. It keys on
    the subject of the event (the finding, the scan run, the board task) — NOT on a
    timestamp or a random id, or every retry would look like a new event.

    Falls back to a hash of the sorted metadata when nothing identifying is present,
    which still dedups an identical redelivery while never colliding across events.
    """
    meta = metadata or {}
    for key in _IDENTITY_KEYS:
        value = str(meta.get(key) or "").strip()
        if value:
            return f"{workspace_id}:{event_key}:{key}={value}"

    digest_source = repr(sorted((str(k), str(v)) for k, v in meta.items()))
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:32]
    return f"{workspace_id}:{event_key}:sha={digest}"


def is_kev(metadata: dict | None) -> bool:
    """True when the event concerns a known-exploited vulnerability.

    KEV bypasses a channel's severity floor (ADR 0016 D5) — an actively exploited
    finding is never noise, whatever the operator set the dial to.
    """
    meta = metadata or {}
    return bool(meta.get("in_kev") or (meta.get("risk") or {}).get("in_kev"))


def is_new_observation(metadata: dict | None) -> bool:
    """False only when the dispatch explicitly marks a re-observation.

    ``FindingRaised.is_new`` exists so consumers can skip steady-state noise. The
    default is True so an event that simply doesn't carry the flag (a draft PR, a
    scan digest) is not silently suppressed.
    """
    meta = metadata or {}
    if "is_new" not in meta:
        return True
    return bool(meta.get("is_new"))
