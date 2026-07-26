"""Composition root: which ScannerPort adapter runs a cloud-posture scan."""

from __future__ import annotations

from components.shared_kernel.application.ports.scanner_port import ScannerPort


def build_scanner() -> ScannerPort:
    """The CSPM scanner. Today Prowler; swapping engines is swapping this adapter."""
    from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner

    return ProwlerScanner()
