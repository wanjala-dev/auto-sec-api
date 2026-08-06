"""ScannerPort — the seam every scanning pillar plugs into (ADR 0004 D3/C5).

A scanner (Prowler for CSPM, Trivy for SCA, …) is a *tool the app drives*, so it is a
driven adapter behind this port. The port is shaped to the Application Core's need —
"given a target, produce normalized findings" — not to any one tool's CLI. Each pillar
implements a driven adapter that runs its engine and maps the output to the shared
``NormalizedFinding`` shape; adding a pillar is a new adapter, never a new pipeline.

Lives in the shared kernel because it is the cross-pillar contract multiple contexts
implement + consume — neither the caller nor a new scanner couples to another context.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from components.shared_kernel.domain.security import NormalizedFinding


@dataclass(frozen=True)
class ScanTarget:
    """What to scan, in the core's terms. ``credentials`` is an opaque, already-vended
    credential envelope (the credential-vending seam owns how it's obtained); the
    adapter knows how to hand it to its engine. ``params`` carries pillar-specific
    scope (regions for CSPM, an image ref for a container scan) without widening the
    contract per pillar.
    """

    identifier: str  # the account id / image / repo the scan is scoped to
    credentials: dict | None = None
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScanArtifact:
    """A scan by-product that is not a finding — an SBOM, a raw engine report.

    Carried on the ``ScanResult`` so a pillar's post-ingest hook can persist it
    (object storage + a ref row) without widening the finding pipeline. ``kind``
    is a stable dotted key (e.g. ``"sbom.cyclonedx"``); ``content`` is the full
    artifact body (text — JSON for every current kind).
    """

    kind: str  # e.g. "sbom.cyclonedx"
    media_type: str  # e.g. "application/vnd.cyclonedx+json"
    content: str


@dataclass(frozen=True)
class ScanResult:
    """A scanner's output: the actionable findings + scan-level counts.

    ``findings`` are the actionable ones (a "finding" is actionable by definition);
    the counts describe the whole run so a pillar snapshot can record pass/total even
    though passing checks are not findings. ``artifacts`` are optional non-finding
    by-products (an image SBOM) a pillar's post-ingest hook persists.
    """

    findings: tuple[NormalizedFinding, ...]
    engine: str  # "prowler", "trivy", …
    engine_version: str = ""
    total_checks: int = 0
    passed_count: int = 0
    failed_count: int = 0
    artifacts: tuple[ScanArtifact, ...] = ()


# A progress reporter the runner may call with a float 0–100.
ProgressCallback = Callable[[float], None]


class ScannerPort:
    """Interface (structural): implement ``scan`` to be a scanner adapter.

    Kept as a plain class with a ``NotImplementedError`` body rather than an ABC so an
    adapter can subclass or merely duck-type it — the composition root wires whichever
    adapter fits the pillar.
    """

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        raise NotImplementedError
