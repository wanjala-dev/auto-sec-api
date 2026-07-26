"""Test helper: a ScanExecutionBackend stub that replays canned OCSF records.

Lets the Prowler scanner tests exercise the *real* ProwlerScanner + records_to_scan_result
without a Prowler install — the stub feeds the runner's stdout protocol
(``{"t":"progress"}`` then ``{"t":"result","records":[...]}``) to ``on_output_line``,
exactly as the real backend does. Not a pytest module (leading underscore → not collected).
"""

from __future__ import annotations

import json

from components.scanning.application.ports.scan_execution_backend import ScanJobResult


class RecordsBackend:
    """A ``ScanExecutionBackend`` that yields ``records`` via the stdout protocol."""

    def __init__(self, records: list):
        self._records = records
        self.calls: list = []  # captured ScanJobSpecs, for assertions

    def run(self, spec, *, on_progress=None, on_output_line=None) -> ScanJobResult:
        self.calls.append(spec)
        if on_output_line is not None:
            on_output_line(json.dumps({"t": "progress", "pct": 50.0}))
            on_output_line(json.dumps({"t": "result", "records": self._records}))
            on_output_line(json.dumps({"t": "done", "count": len(self._records)}))
        return ScanJobResult(stdout="", exit_code=0)
