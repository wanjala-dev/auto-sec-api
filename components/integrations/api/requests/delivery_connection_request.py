"""Input DTOs for delivery-connection CRUD (ADR 0016 D2).

Validation is deliberately strict at the edge: a connection that cannot possibly
deliver must be rejected at create time, not discovered when an alert silently fails
to arrive at 3am. That means per-``auth_mode`` required fields, a shipped-adapter
check (a ``kind`` in the catalog but without an adapter is a 400, not a dead row), and
the Slack webhook-URL allowlist enforced before anything is ever stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from components.integrations.domain.alert_policy import DEFAULT_MIN_SEVERITY, SEVERITY_NAMES
from components.integrations.domain.delivery_policy import is_slack_webhook_url
from components.shared_kernel.domain.delivery_events import (
    DEFAULT_EXTERNAL_EVENT_KEYS,
    EXTERNAL_EVENT_KEYS,
)

# The catalog vs what actually has an adapter today. Generic webhook / Teams / Discord
# / SMTP are declared kinds with no implementation yet (ADR 0016 D8) — accepting one
# would create a row that can never deliver.
_VALID_KINDS = {"slack", "webhook"}
_ENABLED_KINDS = {"slack"}

_VALID_AUTH_MODES = {"webhook_url", "bot_token"}

# ``error`` is system-owned — only verify/delivery may set it.
_VALID_STATUSES = {"connected", "disabled"}

_MAX_NAME = 120


def _clean(value) -> str:
    return str(value or "").strip()


def _normalize_events(raw) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        return ("__invalid__",)
    return tuple(_clean(item).lower() for item in raw)


def _validate_common(
    *, kind: str, auth_mode: str, secret: str, name: str, min_severity: str, events: tuple[str, ...],
    secret_required: bool,
) -> str | None:
    if not name:
        return "A name is required."
    if len(name) > _MAX_NAME:
        return f"Name must be {_MAX_NAME} characters or fewer."

    if kind not in _VALID_KINDS:
        return f"Unknown channel kind '{kind}'."
    if kind not in _ENABLED_KINDS:
        return f"Channel kind '{kind}' is not available yet."

    if auth_mode not in _VALID_AUTH_MODES:
        return f"Unknown auth mode '{auth_mode}'."

    if secret_required or secret:
        error = _validate_secret(kind=kind, auth_mode=auth_mode, secret=secret)
        if error:
            return error

    if min_severity and min_severity not in SEVERITY_NAMES:
        return f"Unknown severity '{min_severity}'."

    if "__invalid__" in events:
        return "Events must be a list of event keys."
    unknown = [key for key in events if key not in EXTERNAL_EVENT_KEYS]
    if unknown:
        return f"Unknown event key(s): {', '.join(sorted(set(unknown)))}."
    return None


def _validate_secret(*, kind: str, auth_mode: str, secret: str) -> str | None:
    if not secret:
        return "A webhook URL is required." if auth_mode == "webhook_url" else "A bot token is required."
    if kind == "slack" and auth_mode == "webhook_url":
        # Enforced here so a bad URL is never persisted, and again in the adapter so a
        # row edited by any other route still cannot be used to POST somewhere else.
        if not is_slack_webhook_url(secret):
            return "Slack webhook URLs must look like https://hooks.slack.com/services/..."
    return None


@dataclass(frozen=True)
class CreateDeliveryConnectionRequest:
    kind: str
    name: str
    auth_mode: str
    secret: str
    channel: str = ""
    min_severity: str = DEFAULT_MIN_SEVERITY
    events: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXTERNAL_EVENT_KEYS)

    @classmethod
    def from_payload(cls, data: dict) -> CreateDeliveryConnectionRequest:
        raw_events = data.get("events")
        return cls(
            kind=_clean(data.get("kind")).lower() or "slack",
            name=_clean(data.get("name")),
            auth_mode=_clean(data.get("auth_mode")).lower() or "webhook_url",
            secret=_clean(data.get("secret")),
            channel=_clean(data.get("channel")),
            min_severity=_clean(data.get("min_severity")).lower() or DEFAULT_MIN_SEVERITY,
            events=DEFAULT_EXTERNAL_EVENT_KEYS if raw_events is None else _normalize_events(raw_events),
        )

    def validation_error(self) -> str | None:
        error = _validate_common(
            kind=self.kind,
            auth_mode=self.auth_mode,
            secret=self.secret,
            name=self.name,
            min_severity=self.min_severity,
            events=self.events,
            secret_required=True,
        )
        if error:
            return error
        if self.kind == "slack" and self.auth_mode == "bot_token" and not self.channel:
            # A webhook carries its channel in the URL; a bot token does not, so without
            # a channel the message has nowhere to land.
            return "A channel is required when using a bot token."
        return None


@dataclass(frozen=True)
class UpdateDeliveryConnectionRequest:
    """Partial update — every field is optional and ``None`` means "leave as-is".

    An omitted ``secret`` keeps the stored credential; supplying one rotates it.
    """

    name: str | None = None
    auth_mode: str | None = None
    secret: str | None = None
    channel: str | None = None
    min_severity: str | None = None
    events: tuple[str, ...] | None = None
    status: str | None = None
    is_enabled: bool | None = None

    @classmethod
    def from_payload(cls, data: dict) -> UpdateDeliveryConnectionRequest:
        def opt(key: str, *, lower: bool = False) -> str | None:
            if key not in data or data.get(key) is None:
                return None
            value = _clean(data.get(key))
            return value.lower() if lower else value

        raw_events = data.get("events")
        raw_enabled = data.get("is_enabled")
        return cls(
            name=opt("name"),
            auth_mode=opt("auth_mode", lower=True),
            secret=opt("secret"),
            channel=opt("channel"),
            min_severity=opt("min_severity", lower=True),
            events=None if raw_events is None else _normalize_events(raw_events),
            status=opt("status", lower=True),
            is_enabled=None if raw_enabled is None else bool(raw_enabled),
        )

    def validation_error(self) -> str | None:
        if self.name is not None and not self.name:
            return "A name is required."
        if self.name is not None and len(self.name) > _MAX_NAME:
            return f"Name must be {_MAX_NAME} characters or fewer."
        if self.auth_mode is not None and self.auth_mode not in _VALID_AUTH_MODES:
            return f"Unknown auth mode '{self.auth_mode}'."
        if self.min_severity is not None and self.min_severity not in SEVERITY_NAMES:
            return f"Unknown severity '{self.min_severity}'."
        if self.status is not None and self.status not in _VALID_STATUSES:
            return f"Status must be one of: {', '.join(sorted(_VALID_STATUSES))}."
        if self.events is not None:
            if "__invalid__" in self.events:
                return "Events must be a list of event keys."
            unknown = [key for key in self.events if key not in EXTERNAL_EVENT_KEYS]
            if unknown:
                return f"Unknown event key(s): {', '.join(sorted(set(unknown)))}."
        if self.secret:
            # Rotating the credential re-runs the same shape check as create.
            return _validate_secret(
                kind="slack", auth_mode=self.auth_mode or "webhook_url", secret=self.secret
            )
        return None
