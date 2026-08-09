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

# A pillar's optional credential vendor: called BEFORE the scan with
# (workspace_id, target_ref, connection_id, account_id, params) keywords; returns
# the opaque credential envelope for ``ScanTarget.credentials`` (or None). Pillars
# without one use the task's default AWS assume-role vend — this seam exists so a
# non-AWS pillar (code_security → a VCS read token) plugs in without the generic
# task learning any pillar's credential shape.
CredentialsVendor = Callable[..., dict | None]

# A pillar's optional failure hook: called when a run FAILS, with (workspace_id,
# target_ref, connection_id, account_id) keywords. The pillar's chance to degrade
# its own state honestly (cloud_posture marks the account link FAILED — the scan
# attempt IS the per-account role verification). POLICY: best-effort — a hook
# failure is logged by the caller and never changes the task's failure handling.
FailureHook = Callable[..., None]


@dataclass(frozen=True)
class RegisteredScanner:
    factory: Callable[[], ScannerPort]
    queue: str
    # Lazily resolves the pillar's PostIngestHook (via its APPLICATION provider —
    # never its infrastructure), or None when the pillar has no post-ingest step.
    post_ingest_factory: Callable[[], PostIngestHook] | None = None
    # Lazily resolves the pillar's CredentialsVendor, or None for the AWS default.
    credentials_factory: Callable[[], CredentialsVendor] | None = None
    # Lazily resolves the pillar's FailureHook, or None when the pillar has no
    # failure side-effects beyond the FAILED ScanRun row the spine records.
    failure_factory: Callable[[], FailureHook] | None = None


def _container_security_trivy() -> ScannerPort:
    from components.container_security.application.providers.scanner_provider import build_scanner

    return build_scanner()


def _container_security_post_ingest() -> PostIngestHook:
    from components.container_security.application.providers.sbom_provider import (
        build_post_ingest_hook,
    )

    return build_post_ingest_hook()


def _code_security_opengrep() -> ScannerPort:
    from components.code_security.application.providers.scanner_provider import build_scanner

    return build_scanner()


def _code_security_post_ingest() -> PostIngestHook:
    from components.code_security.application.providers.snapshot_provider import (
        build_post_ingest_hook,
    )

    return build_post_ingest_hook()


def _code_security_credentials() -> CredentialsVendor:
    from components.code_security.application.providers.scanner_provider import (
        vend_scan_credentials,
    )

    return vend_scan_credentials


def _cloud_posture_prowler() -> ScannerPort:
    from components.cloud_posture.application.providers.scanner_provider import build_scanner

    return build_scanner()


def _cloud_posture_post_ingest() -> PostIngestHook:
    from components.cloud_posture.application.providers.posture_snapshot_provider import (
        build_post_ingest_hook,
    )

    return build_post_ingest_hook()


def _cloud_posture_failure() -> FailureHook:
    from components.cloud_posture.application.providers.posture_snapshot_provider import (
        build_failure_hook,
    )

    return build_failure_hook()


# source → (adapter factory, isolated worker queue). One line per pillar.
_REGISTRY: dict[str, RegisteredScanner] = {
    "container_security.trivy": RegisteredScanner(
        factory=_container_security_trivy,
        queue="container_security",
        post_ingest_factory=_container_security_post_ingest,
    ),
    "code_security.opengrep": RegisteredScanner(
        factory=_code_security_opengrep,
        queue="code_security",
        post_ingest_factory=_code_security_post_ingest,
        credentials_factory=_code_security_credentials,
    ),
    # The CSPM pillar (audit R1): Prowler rides the same spine as every engine.
    # No credentials_factory — the task's default AWS assume-role vend IS this
    # pillar's credential path (duplicating it in a vendor would be the DRY
    # violation the seam exists to avoid).
    "cloud_posture.prowler": RegisteredScanner(
        factory=_cloud_posture_prowler,
        queue="cloud_posture",
        post_ingest_factory=_cloud_posture_post_ingest,
        failure_factory=_cloud_posture_failure,
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


def credentials_vendor_for(source: str) -> CredentialsVendor | None:
    """Build *source*'s credential vendor, or None → the task's default AWS vend."""
    factory = _entry(source).credentials_factory
    return factory() if factory is not None else None


def failure_hook_for(source: str) -> FailureHook | None:
    """Build *source*'s failure hook, or None when the pillar registers none."""
    factory = _entry(source).failure_factory
    return factory() if factory is not None else None


def is_registered(source: str) -> bool:
    return source in _REGISTRY


def known_sources() -> list[str]:
    return sorted(_REGISTRY)
