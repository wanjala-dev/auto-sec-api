"""Composition root — the registry mapping artifact_type -> SignOffPort adapter.

Mirrors ``recycle_bin``'s SoftDeleteProvider: a lazily-initialised singleton
each owning context registers its adapter with. Phase 1 ships the registry
empty (adapters land in Phases 2-5); tests register fakes directly.
"""

from __future__ import annotations

from components.sign_off.application.ports.sign_off_port import SignOffPort
from components.sign_off.domain.errors import UnregisteredArtifactError


class SignOffRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SignOffPort] = {}

    def register(self, adapter: SignOffPort) -> None:
        self._adapters[adapter.artifact_type()] = adapter

    def get_adapter(self, artifact_type: str) -> SignOffPort:
        try:
            return self._adapters[artifact_type]
        except KeyError as exc:
            raise UnregisteredArtifactError(artifact_type) from exc

    def supported_types(self) -> tuple[str, ...]:
        return tuple(self._adapters)


_registry: SignOffRegistry | None = None


def get_sign_off_registry() -> SignOffRegistry:
    """Return the process-wide registry, creating it on first use.

    Owning contexts register their adapters here from their app ``ready()``
    hooks (added per context as Phases 2-5 land).
    """
    global _registry
    if _registry is None:
        _registry = SignOffRegistry()
        # Phase 2-5: register per-context adapters here, e.g.
        #   _registry.register(NewsletterSignOffAdapter())
        #   _registry.register(FinancialReportSignOffAdapter())
    return _registry
