"""The scanner registry — the ONE place a scanning pillar is registered.

Adding a pillar is a single entry here plus its ``ScannerPort`` adapter. Each entry
maps a ``source`` to a factory (which lazily builds the adapter via that pillar's
**application** provider — never its infrastructure, so the cross-context boundary
stays clean) and the Celery queue whose isolated, hardened worker carries that
engine's binary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from components.shared_kernel.application.ports.scanner_port import ScannerPort

# A pillar's optional post-ingest hook: called AFTER a run completes + its findings
# are emitted, with (run_id, workspace_id, target_ref, result). Persists non-finding
# by-products (``ScanResult.artifacts`` — e.g. the Trivy CycloneDX SBOM). POLICY: a
# hook failure must never fail the scan — the caller logs and continues.
PostIngestHook = Callable[..., None]


@dataclass(frozen=True)
class RegisteredScanner:
    factory: Callable[[], ScannerPort]
    queue: str
    # Lazily resolves the pillar's PostIngestHook (via its APPLICATION provider —
    # never its infrastructure), or None when the pillar has no post-ingest step.
    post_ingest_factory: Callable[[], PostIngestHook] | None = None


def _container_security_trivy() -> ScannerPort:
    from components.container_security.application.providers.scanner_provider import build_scanner

    return build_scanner()


def _container_security_post_ingest() -> PostIngestHook:
    from components.container_security.application.providers.sbom_provider import (
        build_post_ingest_hook,
    )

    return build_post_ingest_hook()


# source → (adapter factory, isolated worker queue). One line per pillar.
_REGISTRY: dict[str, RegisteredScanner] = {
    "container_security.trivy": RegisteredScanner(
        factory=_container_security_trivy,
        queue="container_security",
        post_ingest_factory=_container_security_post_ingest,
    ),
}


class UnknownScannerError(KeyError):
    """Raised when a scan is requested for a ``source`` with no registered scanner."""


def _entry(source: str) -> RegisteredScanner:
    try:
        return _REGISTRY[source]
    except KeyError as exc:
        raise UnknownScannerError(source) from exc


def get_scanner(source: str) -> ScannerPort:
    """Build the ``ScannerPort`` adapter registered for *source*."""
    return _entry(source).factory()


def queue_for(source: str) -> str:
    """The Celery queue whose hardened worker runs *source*'s engine."""
    return _entry(source).queue


def post_ingest_for(source: str) -> PostIngestHook | None:
    """Build *source*'s post-ingest hook, or None when the pillar registers none."""
    factory = _entry(source).post_ingest_factory
    return factory() if factory is not None else None


def is_registered(source: str) -> bool:
    return source in _REGISTRY


def known_sources() -> list[str]:
    return sorted(_REGISTRY)
