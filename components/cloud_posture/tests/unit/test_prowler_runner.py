"""Unit tests for the Prowler runner adapter (no AWS, no real Prowler).

Mocks the subprocess so we verify the command construction, credential env, and
the OCSF glob/parse without invoking Prowler.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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

_RUN = "components.cloud_posture.infrastructure.adapters.prowler_runner.subprocess.run"


def _write_ocsf(cmd, **kwargs):
    out_dir = cmd[cmd.index("--output-directory") + 1]
    name = cmd[cmd.index("--output-filename") + 1]
    Path(out_dir, f"{name}.ocsf.json").write_text(json.dumps(_FAKE_OCSF))
    return MagicMock(returncode=0)


def test_run_prowler_builds_command_and_parses_ocsf():
    with patch(_RUN, side_effect=_write_ocsf) as mock_run:
        records = run_prowler(
            credentials=_CREDS, account_id="123456789012", regions=["us-east-1"], prowler_bin="prowler"
        )

    assert records == _FAKE_OCSF
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "prowler"
    assert "json-ocsf" in cmd
    assert "--ignore-exit-code-3" in cmd
    assert "us-east-1" in cmd
    # Assumed-role temp creds are passed via env (never a long-lived key).
    assert mock_run.call_args.kwargs["env"]["AWS_SESSION_TOKEN"] == "token"


def test_run_prowler_returns_empty_when_no_output():
    with patch(_RUN, return_value=MagicMock(returncode=1)):
        records = run_prowler(credentials=_CREDS, account_id="123456789012", prowler_bin="prowler")
    assert records == []
