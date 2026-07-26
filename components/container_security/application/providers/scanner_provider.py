"""Composition root: the container-security scanner (ADR 0006 D4).

Builds ``TrivyScanner`` wired to whichever ``ScanExecutionBackend`` the environment
selects. Referenced by the scanning registry (source ``container_security.trivy``).
"""

from __future__ import annotations

from components.shared_kernel.application.ports.scanner_port import ScannerPort


def build_scanner() -> ScannerPort:
    from components.container_security.infrastructure.adapters.trivy_scanner import TrivyScanner
    from components.scanning.application.providers.execution_backend_provider import (
        build_execution_backend,
    )

    return TrivyScanner(backend=build_execution_backend())
