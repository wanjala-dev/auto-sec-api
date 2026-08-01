"""Canonical allowlist of gated agent capabilities (``Agent.config.capabilities``).

A capability is an AUTHORIZATION surface: flipping it ``True`` unlocks a
risk-gated tool the agent may otherwise never invoke (e.g. ``open_draft_pr``
lets the triage agent open a draft PR against an allowlisted repo). This is the
ONE source of truth for which keys are accepted — both the per-agent patch
surface (``OrmAgentProfileRepository.patch_agent_capabilities``) and the
workspace-level owner toggle (``SetWorkspaceAgentCapabilityUseCase``) validate
against it, so a new capability is added HERE once and everywhere agrees.

Adding a capability means adding it here AND wiring the tool/use case that
reads it — never accept an arbitrary key, because an unread key is a grant that
does nothing but looks live in the UI, and a mistyped key silently no-ops the
gate it was meant to open.
"""

from __future__ import annotations

# The agent type that owns the draft-PR remediation loop (ADR 0010). The
# workspace-level toggle ensures/reads THIS row's capabilities.
TRIAGE_AGENT_TYPE = "triage_agent"

# The single accepted capability-key set. Frozen so callers can't mutate it.
ALLOWED_AGENT_CAPABILITIES: frozenset[str] = frozenset({"open_draft_pr"})
