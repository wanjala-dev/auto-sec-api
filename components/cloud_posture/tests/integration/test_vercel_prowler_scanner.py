"""The Vercel posture scan seam (ADR 0021 D3/D4) — hermetic, fixture-driven.

The fixture mirrors the OCSF shape the pinned engine (5.36.0) emits for the
``vercel`` provider — field placement verified against the 5.36.0 source, not
guessed: ``cloud.account.uid`` = the team id (``finding.py``'s vercel branch maps
``identity.team.id`` into ``account_uid``), ``cloud.region`` = ``"global"``,
``metadata.event_code`` = the check id, ``status_code`` ∈ PASS/FAIL/MANUAL, and
``resources[0]`` carries the project/team resource. The pinned image was also run
with ``prowler vercel --list-checks`` and lists exactly the 26 documented checks.
A live-team capture (G0c) is the named follow-up gated on a Viewer token.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.domain.scan_targets import InvalidVercelScanTargetError
from components.cloud_posture.infrastructure.adapters.prowler_scanner import ProwlerScanner
from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend
from components.shared_kernel.application.ports.scanner_port import ScanTarget

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_vercel_ocsf_sample.json"
_TEAM = "team_abc123DEF456"


def _records():
    return json.loads(_FIXTURE.read_text())


def _target(**overrides):
    kwargs = {
        "identifier": _TEAM,
        "credentials": {"token": "vc_e2e_token"},
        "params": {"provider": "vercel"},
    }
    kwargs.update(overrides)
    return ScanTarget(**kwargs)


@pytest.mark.unit
def test_vercel_scan_runs_the_engine_with_the_pinned_team():
    backend = RecordsBackend(_records())
    result = ProwlerScanner(backend=backend).scan(_target())

    assert len(backend.calls) == 1
    spec = backend.calls[0]
    assert spec.source == "cloud_posture.prowler.vercel"
    script = spec.args[-1]  # ("sh", "-c", <script>)
    assert "prowler vercel" in script
    assert "--output-formats json-ocsf" in script
    # The team NEVER enters argv — it rides the env pin; the token never leaves secret_env.
    assert _TEAM not in script
    assert "vc_e2e_token" not in script
    assert spec.secret_env == {"VERCEL_TOKEN": "vc_e2e_token", "VERCEL_TEAM": _TEAM}
    assert spec.run_as_user == 1000  # the official prowler image's non-root uid
    # Deliberately NOT the AWS 4Gi bump — a team estate fits the backend default (D3).
    assert spec.memory_limit is None

    # Counts: 4 checks = 1 PASS + 2 FAIL + 1 MANUAL; findings = the 3 actionable.
    assert result.total_checks == 4
    assert result.passed_count == 1
    assert result.failed_count == 2
    assert len(result.findings) == 3


@pytest.mark.unit
def test_vercel_findings_carry_vercel_identity_never_aws():
    result = ProwlerScanner(backend=RecordsBackend(_records())).scan(_target())
    by_check = {f.attributes["check_id"]: f for f in result.findings}

    secrets = by_check["project_environment_no_secrets_in_plain_type"]
    assert secrets.source == "cloud_posture.prowler.vercel"
    # The URN namespace is the trap this ADR exists to close: urn:vercel:, NEVER aws.
    assert secrets.asset_urn == "urn:vercel:prj_a1b2c3d4e5f6"
    # Fingerprint identity key = the TEAM id (OCSF cloud.account.uid), not an AWS account.
    assert secrets.fingerprint == f"project_environment_no_secrets_in_plain_type|{_TEAM}|prj_a1b2c3d4e5f6"
    assert secrets.attributes["team_id"] == _TEAM
    assert secrets.attributes["account_id"] == _TEAM
    assert secrets.attributes["service"] == "project"

    team_check = by_check["team_member_role_least_privilege"]
    assert team_check.asset_urn == f"urn:vercel:{_TEAM}"

    for finding in result.findings:
        assert not finding.asset_urn.startswith("arn:aws"), "a Vercel finding wearing an AWS URN corrupts the spine"
        assert finding.source == "cloud_posture.prowler.vercel"


@pytest.mark.unit
def test_manual_checks_surface_honestly_not_as_pass_and_not_vanished():
    """The 5 firewall checks return MANUAL under a reduced-privilege token (R4):
    they must stay actionable findings carrying their MANUAL status — never a
    silent PASS, never dropped."""
    result = ProwlerScanner(backend=RecordsBackend(_records())).scan(_target())
    by_check = {f.attributes["check_id"]: f for f in result.findings}

    waf = by_check["security_waf_enabled"]
    assert waf.attributes["check_status"] == "manual"
    # And the PASS check is correctly NOT a finding (a pass is not actionable).
    assert "project_directory_listing_disabled" not in by_check


@pytest.mark.unit
def test_scan_without_a_team_is_rejected_before_the_engine_runs():
    # Blank team = Prowler auto-discovers every team the token's user belongs to —
    # the consent violation D3 forbids. Rejected at the gate, no Job dispatched.
    backend = RecordsBackend(_records())
    with pytest.raises(InvalidVercelScanTargetError):
        ProwlerScanner(backend=backend).scan(_target(identifier=""))
    assert backend.calls == []


@pytest.mark.unit
def test_vercel_source_is_registered_on_the_scanning_spine():
    """The pillar rides the spine (scanner registry + cloud_posture queue) — the
    gate/cooldown/provenance machinery all key off this registration."""
    from components.scanning.application.providers.scanner_registry import (
        is_registered,
        queue_for,
    )

    assert is_registered("cloud_posture.prowler.vercel")
    assert queue_for("cloud_posture.prowler.vercel") == "cloud_posture"
