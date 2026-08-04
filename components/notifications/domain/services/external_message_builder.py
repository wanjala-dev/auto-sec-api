"""Build the message that leaves the tenant — the ONE redaction point (ADR 0016 D6).

Every external delivery is rendered here and nowhere else, so the redaction rule has
a single enforcement point that can be unit-tested against representative metadata.
Adapters only *format* what this produces; they never reach into metadata themselves.

**The rule.** A Slack channel's membership is invisible to us, so treat every message
as world-readable. What may leave: a title, a verb, a severity, an asset URN, counts,
and an absolute deep link back into the product. What may never leave: prompts, tool
inputs/outputs, raw finding payloads or ``attributes``, log lines, tokens, secrets.

That is the same Option-A line the agents surface already draws — deep-run detail is
owner-only in-app, so it certainly does not belong in a third-party chat service.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.shared_kernel.domain.delivery_events import (
    DRAFT_PR_OPENED,
    FINDING_CRITICAL,
    RISK_ACCEPT_EXPIRING,
    SCAN_DIGEST,
    SCAN_FAILED,
)

_SEVERITY_EMOJI = {
    "critical": "🚨",
    "high": "🔴",
    "medium": "🟠",
    "low": "🟡",
    "informational": "⚪",
}

# The ONLY metadata keys allowed onto an external message, per event class. Anything
# not named here is dropped — an allowlist, so a new metadata key added upstream
# cannot silently start leaving the tenant.
_ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
    DRAFT_PR_OPENED: ("repo", "pr_url"),
    FINDING_CRITICAL: ("asset_urn", "source", "severity"),
    SCAN_FAILED: ("engine", "account_id", "reason"),
    SCAN_DIGEST: ("engine", "critical", "high", "medium", "low", "total"),
    RISK_ACCEPT_EXPIRING: ("asset_urn", "expires_at"),
}

_TITLE_MAX = 250
_BODY_MAX = 2000
_VALUE_MAX = 200


@dataclass(frozen=True)
class ExternalMessage:
    """A rendered, redacted message plus the routing facts the leg needs."""

    title: str
    body: str
    severity: str = ""
    link: str = ""
    fields: dict = field(default_factory=dict)


def build_message(
    *,
    event_key: str,
    verb: str,
    metadata: dict | None,
    link: str = "",
) -> ExternalMessage:
    """Render one external message. Never raises — a malformed dispatch degrades
    to a plain title rather than blocking delivery of a real security event."""
    meta = metadata or {}
    severity = str(meta.get("severity") or "").strip().lower()

    title = _title_for(event_key, verb=verb, severity=severity, meta=meta)
    fields = _safe_fields(event_key, meta)
    body = _body_for(event_key, fields=fields, meta=meta)

    return ExternalMessage(
        title=title[:_TITLE_MAX],
        body=body[:_BODY_MAX],
        severity=severity,
        link=link or "",
        fields=fields,
    )


def _title_for(event_key: str, *, verb: str, severity: str, meta: dict) -> str:
    if event_key == FINDING_CRITICAL:
        emoji = _SEVERITY_EMOJI.get(severity, "•")
        label = severity.title() or "New"
        return f"{emoji} {label} finding: {_clean(verb)}"
    if event_key == DRAFT_PR_OPENED:
        return f"🔧 Draft PR opened for review: {_clean(verb)}"
    if event_key == SCAN_FAILED:
        return f"⚠️ Scan failed: {_clean(meta.get('engine')) or 'a scan engine'}"
    if event_key == SCAN_DIGEST:
        engine = _clean(meta.get("engine")) or "Scan"
        return f"📋 {engine} scan completed"
    if event_key == RISK_ACCEPT_EXPIRING:
        return f"⏳ Risk acceptance expiring: {_clean(verb)}"
    return _clean(verb) or "Auto-Sec event"


def _body_for(event_key: str, *, fields: dict, meta: dict) -> str:
    if event_key == SCAN_DIGEST:
        # The batch rule made legible: ONE message per scan with counts, never one
        # message per finding (ADR 0016 D5).
        counts = " / ".join(
            f"{fields[k]} {k}" for k in ("critical", "high", "medium", "low") if fields.get(k)
        )
        return counts or "No new findings."
    lines = [f"{key.replace('_', ' ').title()}: {value}" for key, value in fields.items()]
    return "\n".join(lines)


def _safe_fields(event_key: str, meta: dict) -> dict:
    """Allowlist projection — the redaction rule, mechanically applied."""
    allowed = _ALLOWED_FIELDS.get(event_key, ())
    out: dict = {}
    for key in allowed:
        value = meta.get(key)
        if value in (None, "", [], {}):
            continue
        out[key] = _clean(value)
    return out


def _clean(value) -> str:
    """Coerce to a short single-line string. Newlines are stripped so a crafted
    log line cannot forge extra lines in a chat message."""
    text = str(value if value is not None else "")
    return " ".join(text.split())[:_VALUE_MAX]
