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


@dataclass(frozen=True)
class RegisteredScanner:
    factory: Callable[[], ScannerPort]
    queue: str


def _container_security_trivy() -> ScannerPort:
    from components.container_security.application.providers.scanner_provider import build_scanner

    return build_scanner()


# source → (adapter factory, isolated worker queue). One line per pillar.
_REGISTRY: dict[str, RegisteredScanner] = {
    "container_security.trivy": RegisteredScanner(
        factory=_container_security_trivy,
        queue="container_security",
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


def is_registered(source: str) -> bool:
    return source in _REGISTRY


def known_sources() -> list[str]:
    return sorted(_REGISTRY)
