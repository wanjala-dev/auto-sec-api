"""Request DTOs: create / update a WorkspaceLogSource (ADR 0008 Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field

_VALID_KINDS = {"s3", "cloudwatch", "datadog", "splunk", "webhook"}
# Kinds with a shipped adapter, selectable via the API. CloudWatch (Phase 4) is
# additionally gated at the provider by ``feature.log_source_cloudwatch``; Datadog/
# Splunk stay catalog-only until their adapters land.
_ENABLED_KINDS = {"s3", "cloudwatch"}
_VALID_STATUSES = {"draft", "active", "error", "disabled"}


@dataclass(frozen=True)
class CreateLogSourceRequest:
    """Validated input for ``POST /integrations/workspaces/<ws>/log-sources/``."""

    kind: str
    name: str = ""
    config: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, data: dict) -> CreateLogSourceRequest:
        data = data or {}
        return cls(
            kind=str(data.get("kind") or "").strip().lower(),
            name=str(data.get("name") or "").strip(),
            config=dict(data.get("config") or {}),
        )

    def validation_error(self) -> str | None:
        if self.kind not in _VALID_KINDS:
            return f"kind must be one of {sorted(_VALID_KINDS)}."
        if self.kind not in _ENABLED_KINDS:
            return f"The {self.kind} log source is not available yet."
        if self.kind == "s3":
            if not str(self.config.get("aws_connection_id") or "").strip():
                return "S3 log source requires config.aws_connection_id."
            if not str(self.config.get("bucket") or "").strip():
                return "S3 log source requires config.bucket."
        if self.kind == "cloudwatch":
            if not str(self.config.get("aws_connection_id") or "").strip():
                return "CloudWatch log source requires config.aws_connection_id."
            if not str(self.config.get("log_group") or "").strip():
                return "CloudWatch log source requires config.log_group."
        return None


@dataclass(frozen=True)
class UpdateLogSourceRequest:
    """Partial update — only supplied fields are applied. ``None`` means 'leave as-is'."""

    name: str | None = None
    config: dict | None = None
    status: str | None = None

    @classmethod
    def from_payload(cls, data: dict) -> UpdateLogSourceRequest:
        data = data or {}
        name = data.get("name")
        config = data.get("config")
        status = data.get("status")
        return cls(
            name=None if name is None else str(name).strip(),
            config=None if config is None else dict(config),
            status=None if status is None else str(status).strip().lower(),
        )

    def validation_error(self) -> str | None:
        if self.status is not None and self.status not in _VALID_STATUSES:
            return f"status must be one of {sorted(_VALID_STATUSES)}."
        # A workspace can only toggle enable/disable via the API; draft/error are
        # lifecycle states the system owns (set by create / verify).
        if self.status in {"draft", "error"}:
            return "status can only be set to 'active' or 'disabled' via the API."
        return None
