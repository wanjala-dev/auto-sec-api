"""Composition root: which ScannerPort adapter runs a cloud-posture scan."""

from __future__ import annotations

from components.shared_kernel.application.ports.scanner_port import ScannerPort


def build_scanner() -> ScannerPort:
    """The CSPM scanner. Today Prowler on the shared ScanExecutionBackend (ADR 0006);
    swapping engines is swapping this adapter, swapping *where* it runs is the backend."""
    from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner
    from components.scanning.application.providers.execution_backend_provider import (
        build_execution_backend,
    )

    return ProwlerScanner(backend=build_execution_backend())
