"""Scanning domain errors — part of the shared error taxonomy."""

from __future__ import annotations

from components.shared_kernel.domain.errors import DomainError, ValidationError


class ScanError(DomainError):
    """Base class for scanning-domain errors."""


class InvalidScanSpecError(ScanError, ValidationError):
    """A scan job specification is invalid (missing image/args, etc.)."""
