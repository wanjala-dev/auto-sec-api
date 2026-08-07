"""Composition root: the code-security scanner + its credential vend (ADR 0019 D2).

Referenced by the scanning registry (source ``code_security.opengrep``):

- ``build_scanner``          — OpengrepScanner on whichever ScanExecutionBackend the
  environment selects (the TrivyScanner wiring, third instance).
- ``vend_scan_credentials``  — the per-source credential factory the generic scan
  task resolves instead of its AWS default: repo read access through the ADR 0010
  VcsConnection seam (allowlist fail-closed, short-lived token, resolved SHA).
"""

from __future__ import annotations

from components.shared_kernel.application.ports.scanner_port import ScannerPort


def build_scanner() -> ScannerPort:
    from components.code_security.infrastructure.adapters.opengrep_scanner import OpengrepScanner
    from components.scanning.application.providers.execution_backend_provider import (
        build_execution_backend,
    )

    return OpengrepScanner(backend=build_execution_backend())


def vend_scan_credentials(
    *, workspace_id, target_ref: str, connection_id: str | None = None, account_id: str = "", params: dict | None = None
) -> dict | None:
    """Vend the Opengrep Job's credential envelope for ``target_ref`` (owner/repo).

    Delegates to the integrations-owned seam so all VcsConnection/allowlist/token
    knowledge stays with its owner. ``None`` (repo not allowlisted, no token) makes
    the scan fail loud in the adapter — never a consentless scan.
    """
    from components.integrations.application.providers.vcs_scan_access_provider import (
        vend_repo_read_access,
    )

    return vend_repo_read_access(workspace_id=workspace_id, repo=target_ref, connection_id=connection_id)
