"""Unit tests for the Prowler runner adapter (no AWS, no real Prowler).

Mocks ``subprocess.Popen`` so we verify the SDK-runner command, that streamed
progress lines reach the callback, and that the OCSF file is parsed — without
invoking Prowler.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from components.cloud_posture.infrastructure.adapters.prowler_runner import run_prowler

pytestmark = pytest.mark.unit

_CREDS = {"AccessKeyId": "AKIA", "SecretAccessKey": "secret", "SessionToken": "token"}
_FAKE_OCSF = [
    {
        "metadata": {"event_code": "s3_bucket_public_access"},
        "status_code": "FAIL",
        "severity": "High",
        "finding_info": {"uid": "u", "title": "public bucket"},
        "resources": [{"uid": "arn:aws:s3:::b", "group": {"name": "s3"}}],
        "cloud": {"account": {"uid": "123456789012"}},
    }
]

_POPEN = "components.cloud_posture.infrastructure.adapters.prowler_runner.subprocess.Popen"


class _FakeProc:
    def __init__(self, lines, write_ocsf_to=None):
        self.stdout = iter(lines)
        if write_ocsf_to is not None:
            Path(write_ocsf_to).write_text(json.dumps(_FAKE_OCSF))

    def wait(self, timeout=None):
        return 0


def test_run_prowler_streams_progress_and_parses_ocsf():
    seen: list[float] = []
    lines = [
        json.dumps({"t": "progress", "pct": 10.0}) + "\n",
        json.dumps({"t": "progress", "pct": 55.0}) + "\n",
        json.dumps({"t": "done", "count": 1}) + "\n",
    ]

    captured = {}

    def _popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env", {})
        return _FakeProc(lines, write_ocsf_to=cmd[-1])  # last arg = OCSF out file

    with patch(_POPEN, side_effect=_popen):
        records = run_prowler(
            credentials=_CREDS,
            account_id="123456789012",
            regions=["us-east-1"],
            progress_callback=seen.append,
        )

    assert records == _FAKE_OCSF
    assert seen == [10.0, 55.0]  # progress lines forwarded; "done" is not progress
    cmd = captured["cmd"]
    assert cmd[1].endswith("prowler_sdk_runner.py")
    assert cmd[2] == "123456789012"
    assert cmd[3] == "us-east-1"
    # Assumed-role temp creds are passed via env (never a long-lived key).
    assert captured["env"]["AWS_SESSION_TOKEN"] == "token"


def test_run_prowler_returns_empty_when_no_ocsf():
    lines = [json.dumps({"t": "error", "message": "boom"}) + "\n"]

    with patch(_POPEN, side_effect=lambda cmd, **kw: _FakeProc(lines)):  # no OCSF written
        records = run_prowler(credentials=_CREDS, account_id="123456789012")

    assert records == []
