"""Pure delivery-target policy — which outbound URLs we are willing to POST to.

No framework, no IO. Sibling of ``alert_policy`` (the severity gate); this is the
destination gate.

This lives in the domain rather than inside the Slack adapter because two very
different callers need the same answer: the API validates a pasted URL before it is
ever stored, and the adapter re-checks before it makes a request. Putting the rule in
the adapter would force the API layer to import concrete infrastructure — a boundary
break the architecture tests correctly reject — and would leave the rule reachable
only through the thing it is supposed to constrain.
"""

from __future__ import annotations

from urllib.parse import urlparse

SLACK_WEBHOOK_HOST = "hooks.slack.com"
SLACK_WEBHOOK_PATH_PREFIX = "/services/"


def is_slack_webhook_url(url: str) -> bool:
    """True when ``url`` is a Slack incoming-webhook URL.

    Strict allowlist (ADR 0016 D6): https only, the exact host — never a suffix like
    ``hooks.slack.com.evil.test`` — and a non-empty ``/services/`` path. A known
    destination set is OWASP's strongest SSRF posture, which is why this kind needs no
    generic resolve-and-deny guard.
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == SLACK_WEBHOOK_HOST
        and parsed.path.startswith(SLACK_WEBHOOK_PATH_PREFIX)
        and len(parsed.path) > len(SLACK_WEBHOOK_PATH_PREFIX)
    )
