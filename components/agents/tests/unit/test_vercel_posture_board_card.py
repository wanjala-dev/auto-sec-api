"""The Vercel posture board card (ADR 0021 D4) — copy, honesty, and routing discipline."""

from __future__ import annotations

import types

import pytest

from components.agents.application.handlers.finding_raised_board_handler import (
    _SOURCE_BOARD,
    _build_vercel_posture_card,
)
from components.shared_kernel.domain.triage import ROUTABLE_SOURCE_TYPES

pytestmark = pytest.mark.unit

_SOURCE = "cloud_posture.prowler.vercel"
_MAPPING = _SOURCE_BOARD[_SOURCE]


def _finding(check_status="fail", severity="high"):
    return types.SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000aa",
        title="Vercel project has no secret-like environment variables stored as plain text",
        description="Plaintext secrets are readable by anyone with project access.",
        remediation="Re-create the variables with the Sensitive type.",
        compliance={"CIS-Controls-8.1": ["3.11"]},
        fingerprint="project_environment_no_secrets_in_plain_type|team_abc123|prj_x",
        severity=types.SimpleNamespace(value=severity),
        attributes={
            "check_id": "project_environment_no_secrets_in_plain_type",
            "check_status": check_status,
            "team_id": "team_abc123",
            "account_id": "team_abc123",
            "service": "project",
            "resource_uid": "prj_x",
            "resource_name": "web-app",
            "resource_type": "Project",
        },
    )


def _event():
    return types.SimpleNamespace(
        workspace_id="00000000-0000-0000-0000-00000000000a",
        finding_id="00000000-0000-0000-0000-0000000000aa",
        source=_SOURCE,
    )


def test_mapping_is_registered_with_the_high_board_floor():
    assert _MAPPING["source_type"] == "ai.vercel_posture"
    assert _MAPPING["min_severity"] == "high"
    # Deliberately NOT routable in P0 — no triage tool exists yet, and "routable
    # without a tool is a silent no-op" (the strand-guard rule from #276).
    assert "ai.vercel_posture" not in ROUTABLE_SOURCE_TYPES


def test_card_leads_with_check_and_project_and_stays_operator_material():
    card = _build_vercel_posture_card(_finding(), _event(), _MAPPING)
    assert card["agent_type"] == "ai_teammate"  # operator reading material (non-routable)
    assert card["title"].startswith("High:")
    assert "web-app" in card["summary"] and "team_abc123" in card["summary"]
    assert card["payload"]["team_id"] == "team_abc123"
    assert card["payload"]["confidence"] == "high"
    assert card["lookup_key"] == card["payload"]["lookup_key"] == _finding().fingerprint
    assert card["context"]["kind"] == "vercel_posture"


def test_manual_check_is_labelled_manual_and_downgraded_to_medium_confidence():
    # A MANUAL check (firewall endpoint inaccessible under this token, R4) must
    # surface honestly — labelled, lower confidence, never a PASS, never dropped.
    card = _build_vercel_posture_card(_finding(check_status="manual"), _event(), _MAPPING)
    assert card["summary"].startswith("MANUAL")
    assert card["payload"]["confidence"] == "medium"
    assert card["payload"]["check_status"] == "manual"
    assert "status: manual" in card["payload"]["evidence"][-1]
