"""Test helper: a ScanExecutionBackend stub that replays canned OCSF records.

Lets the Prowler scanner tests exercise the *real* ProwlerScanner + records_to_scan_result
without a Prowler install — the stub returns the OCSF records as the Job's ``stdout`` (a JSON
array), exactly as the official-Prowler Job does (it ``cat``s its OCSF file to stdout). Not a
pytest module (leading underscore → not collected).
"""

from __future__ import annotations

import json

from components.scanning.application.ports.scan_execution_backend import ScanJobResult


class RecordsBackend:
    """A ``ScanExecutionBackend`` that yields ``records`` as the OCSF JSON array on stdout."""

    def __init__(self, records: list):
        self._records = records
        self.calls: list = []  # captured ScanJobSpecs, for assertions

    def run(self, spec, *, on_progress=None, on_output_line=None) -> ScanJobResult:
        self.calls.append(spec)
        return ScanJobResult(stdout=json.dumps(self._records), exit_code=0)
