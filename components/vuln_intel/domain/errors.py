"""Domain errors for the vuln_intel module — extend the shared taxonomy."""

from __future__ import annotations

from components.shared_kernel.domain.errors import IntegrationError


class VulnIntelError(IntegrationError):
    """Base error for the threat-intel module — a third-party feed integration concern."""


class MalformedFeedError(VulnIntelError):
    """A feed pull was structurally invalid (e.g. a KEV catalog with no version) and
    cannot be persisted as a reproducible, version-stamped snapshot (ADR 0013 D2)."""
