"""ProwlerScanner — the CSPM ScannerPort adapter (ADR 0006 D4, provider-keyed per ADR 0021).

Runs the **official Prowler image** with its **native `-M json-ocsf` CLI** and parses the OCSF it
emits — the same shape as ``TrivyScanner`` (build argv → ``ScanExecutionBackend`` → parse
``result.stdout``). It deliberately does NOT import Prowler's internal SDK API: the previous
``prowler_sdk_runner.py`` imported ``prowler.lib.*`` / ``AwsProvider`` ("verified in 5.36.0"), which
broke on every Prowler version bump and forced us to build+own an image. Pinning the maintained
official image and using the stable CLI removes that coupling (see ``improve-dont-replicate.md``).

The engine is multi-provider (``prowler aws`` / ``prowler vercel``); WHICH provider comes from the
``PostureProvider`` value object resolved off ``target.params["provider"]`` (ADR 0021 D1) —
it supplies the argv word, the ``ScanJobSpec.source``, the target validator (the injection gate),
the credential env mapping, and the memory profile. Nothing provider-shaped is hardcoded here.

Getting the OCSF out of an ephemeral Job: Prowler writes OCSF to a *file* (no stdout mode), and the
K8sJobBackend collects *stdout* — so the Job runs Prowler then ``cat``s the file to stdout. The only
interpolated inputs are the provider's validated tokens (AWS regions; the Vercel team never enters
argv at all — it rides the ``VERCEL_TEAM`` env var), which closes the shell-injection surface — the
same "validate the untrusted input, then it's safe in the command" gate Trivy uses for its image
ref. Credentials are the already-vended envelope, mounted as ``secret_env`` (never in argv or logs).

Scale note (ADR 0006 D4 follow-up): a full-account OCSF result can exceed pod-log limits and be
truncated (``records_to_scan_result`` then defensively yields fewer/zero findings). The fix — shared
for Trivy too — is an artifact/volume output channel on the backend rather than pod-log stdout.
"""

from __future__ import annotations

import json
import logging
import os

from components.cloud_posture.domain.posture_provider import (
    PostureProvider,
    resolve_posture_provider,
)
from components.scanning.application.ports.scan_execution_backend import (
    ScanExecutionBackend,
    ScanJobSpec,
)
from components.scanning.domain.errors import ScanExecutionError
from components.shared_kernel.application.ports.scanner_port import (
    ProgressCallback,
    ScannerPort,
    ScanResult,
    ScanTarget,
)

logger = logging.getLogger(__name__)

_ENGINE = "prowler"
# The maintained official Prowler image (pinned for reproducible + supply-chain-controlled scans),
# like Trivy's aquasec/trivy pin. Override with PROWLER_IMAGE. The pinned 5.36.0 digest already
# contains the `vercel` provider tree (verified against the 5.36.0 tag — ADR 0021 R2), so both
# posture providers run the SAME image: no bump, no second pin.
_PROWLER_IMAGE = os.environ.get(
    "PROWLER_IMAGE",
    # Pinned by version AND digest (we execute this image — pin-versions.md rule #2). Prowler 5.36.0.
    "toniblyx/prowler:5.36.0@sha256:d37ab7a1d49e56023cf7199b291ec833285e9f3431052fcc2df834f73d81c296",
)
# In the official image the CLI is a venv entrypoint, not on the default PATH; prepend it so the
# script finds `prowler` (and still works if a custom PROWLER_IMAGE has it on PATH).
_PROWLER_BIN_DIR = "/home/prowler/.venv/bin"
# The official image's non-root user (uid 1000); its venv binary is only reachable by that uid, so
# the scan Job must run as it — not the backend's default hardened uid. Stable for the pinned digest.
_PROWLER_UID = 1000


def _memory_limit_for(provider: PostureProvider) -> str | None:
    """The engine container's memory limit for this provider.

    Prowler loads every provider SDK and accumulates an account's findings in-memory across
    all regions; the backend's 2Gi default OOMKills a real AWS scan (→ zero findings,
    silent), so the AWS provider carries a 4Gi override (env-tunable via
    PROWLER_MEMORY_LIMIT for larger estates). A provider WITHOUT an override (Vercel — one
    team, 26 checks) deliberately keeps the backend default; the env knob does not widen it
    (ADR 0021 D3: don't inherit the AWS bump).
    """
    if provider.memory_limit is None:
        return None
    return os.environ.get("PROWLER_MEMORY_LIMIT", provider.memory_limit)


class ProwlerScanner(ScannerPort):
    def __init__(self, backend: ScanExecutionBackend):
        self._backend = backend

    def scan(self, target: ScanTarget, *, on_progress: ProgressCallback | None = None) -> ScanResult:
        from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
            records_to_scan_result,
        )

        provider = resolve_posture_provider(target.params.get("provider"))
        # Strict gate: only well-formed provider tokens reach the command (AWS regions are
        # interpolated; the Vercel team rides env-only but is validated to the same bar).
        identifier, extra_flags = provider.validate_target(target.identifier, target.params)

        # Official Prowler writes OCSF to a file (no stdout mode) → run it, suppress its
        # progress/table output, then cat the OCSF file to stdout for the backend to collect.
        script = (
            f'export PATH="{_PROWLER_BIN_DIR}:$PATH"; '
            f"prowler {provider.token} --output-formats json-ocsf --output-directory /tmp "
            f"--output-filename scan {extra_flags} >/dev/null 2>&1; "
            "cat /tmp/*.ocsf.json 2>/dev/null"
        )

        result = self._backend.run(
            ScanJobSpec(
                source=provider.source,
                image=_PROWLER_IMAGE,
                args=("sh", "-c", script),  # inputs validated above → no injection surface
                env={"HOME": "/tmp"},  # prowler config/cache under the writable /tmp (readOnlyRootFS)
                secret_env=provider.credential_env(target.credentials, identifier),
                run_as_user=_PROWLER_UID,  # the official image's uid; the venv binary needs it
                memory_limit=_memory_limit_for(provider),
            ),
            on_progress=on_progress,  # K8s elapsed-time heartbeat (Prowler has no stdout progress)
        )
        # Fail LOUD, never silent. A Prowler Job that FATAL-errors / OOMKills / times out leaves no
        # (or no complete) OCSF file, so `cat` exits non-zero (or the backend flags timed_out) →
        # result.ok is False. Parsing whatever is on stdout would yield [] → 0 findings, and
        # run_prowler_scan_for_account would then record a COMPLETED CloudPostureScan AND promote
        # the account link to VERIFIED — a crashed scan masquerading as a clean account, the worst
        # failure mode for a security scanner. Raise so the task's `except` marks the link FAILED and
        # reports the run failed (no-shortcuts: a bad scan is a failed scan). The memory_limit note
        # above only *mitigates* the OOM (4Gi headroom); THIS is what actually *surfaces* it.
        if not result.ok:
            snippet = (result.stdout or "").strip().replace("\n", " ")[:300]
            logger.error(
                "prowler_scan_failed provider=%s target=%s exit_code=%s timed_out=%s detail=%s",
                provider.token,
                identifier,
                result.exit_code,
                result.timed_out,
                snippet,
            )
            raise ScanExecutionError(
                f"Prowler {provider.token} scan of {identifier} failed "
                f"(exit_code={result.exit_code}, timed_out={result.timed_out})"
            )
        return records_to_scan_result(_parse_ocsf_stdout(result.stdout), engine_version=_ENGINE, provider=provider)


def _parse_ocsf_stdout(stdout: str | None) -> list:
    """Defensively parse the OCSF JSON array Prowler wrote to stdout.

    Prowler's OCSF output has had validity bugs (prowler-cloud/prowler#3675) and pod-log stdout can
    truncate a large result — either way the JSON may not parse, so return ``[]`` rather than raise
    (``records_to_scan_result`` also skips individual malformed records)."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        logger.warning("prowler OCSF output was not valid JSON (bytes=%d)", len(text))
        return []
    return data if isinstance(data, list) else []
