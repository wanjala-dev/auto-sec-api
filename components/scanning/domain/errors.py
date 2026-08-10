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


class IncompleteScanOutputError(ScanExecutionError):
    """The engine ran, but the result document it produced is unusable.

    The sibling failure to a non-zero exit, and a nastier one: the engine exits **0**
    while its output is empty, truncated (pod-log rotation on a big account), or
    corrupt. Parsing that yields zero findings, so without this error the spine would
    record a COMPLETED run over a mutilated result — a scan that under-reports exactly
    on the largest, most valuable estates.

    A ``ScanExecutionError`` subclass so every existing fail-loud path (adapters,
    ``run_scan_and_ingest``'s FAILED-run + audit handling) already treats it correctly,
    while the distinct type lets callers and tests tell "engine crashed" from "engine's
    output was unusable". Raised only by
    ``components.scanning.domain.engine_output.parse_engine_result_document``.
    """
