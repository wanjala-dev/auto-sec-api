"""Request DTO: toggle a triage-agent capability at the workspace level.

Input for ``PATCH /integrations/workspaces/<ws>/triage-capabilities/`` — the
owner-gated setter that flips ``triage_agent`` ``config.capabilities.<key>``.
``capability`` defaults to ``open_draft_pr`` (the only capability today) so a
bare ``{"enabled": true}`` body Just Works for the FE toggle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetTriageCapabilityRequest:
    capability: str
    enabled: bool

    @classmethod
    def from_payload(cls, data: dict) -> SetTriageCapabilityRequest:
        data = data or {}
        capability = str(data.get("capability") or "open_draft_pr").strip()
        return cls(capability=capability, enabled=cls._coerce_bool(data.get("enabled")))

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def validation_error(self) -> str | None:
        if not self.capability:
            return "capability is required."
        return None
