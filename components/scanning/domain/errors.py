"""Scanning domain errors — part of the shared error taxonomy."""

from __future__ import annotations

from components.shared_kernel.domain.errors import DomainError, ValidationError


class ScanError(DomainError):
    """Base class for scanning-domain errors."""


class InvalidScanSpecError(ScanError, ValidationError):
    """A scan job specification is invalid (missing image/args, etc.)."""


class ScanExecutionError(ScanError):
    """The scanner engine process itself failed — a non-zero exit or a timeout.

    Raising this (rather than parsing whatever partial/error output the engine left on
    stdout) is what stops a crashed scan from masquerading as a clean one: it propagates
    to ``run_scan_and_ingest``, which marks the ``ScanRun`` FAILED and re-raises. A
    security scanner that dies MUST surface as a failed run, never as "0 findings".
    """
