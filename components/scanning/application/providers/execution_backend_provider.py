"""Composition root: which ScanExecutionBackend runs scans (ADR 0006).

``SCAN_EXECUTION_BACKEND=k8s_job`` (the prod substrate — ephemeral gVisor Jobs) or
``local_subprocess`` (dev/CI). Defaults to local_subprocess so nothing depends on a
cluster unless explicitly opted in.
"""

from __future__ import annotations

import os

from components.scanning.application.ports.scan_execution_backend import ScanExecutionBackend


def build_execution_backend() -> ScanExecutionBackend:
    backend = os.environ.get("SCAN_EXECUTION_BACKEND", "local_subprocess").strip().lower()
    if backend == "k8s_job":
        from components.scanning.infrastructure.backends.k8s_job_backend import K8sJobBackend

        return K8sJobBackend()
    from components.scanning.infrastructure.backends.local_subprocess_backend import (
        LocalSubprocessBackend,
    )

    return LocalSubprocessBackend()
