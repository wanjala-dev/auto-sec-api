"""Request DTO validation for the VercelConnection API (ADR 0021 D2)."""

from __future__ import annotations

import pytest

from components.integrations.api.requests.vercel_connection_request import (
    CreateVercelConnectionRequest,
    UpdateVercelConnectionRequest,
)

pytestmark = pytest.mark.unit


class TestCreateVercelConnectionRequest:
    def test_valid_team_id_payload(self):
        req = CreateVercelConnectionRequest.from_payload(
            {"team": "team_abc123DEF456", "token": "vc_tok", "name": "Prod team"}
        )
        assert req.validation_error() is None
        assert req.team_parts == ("team_abc123DEF456", "")

    def test_valid_slug_payload(self):
        req = CreateVercelConnectionRequest.from_payload({"team": "acme-prod", "token": "vc_tok"})
        assert req.validation_error() is None
        assert req.team_parts == ("", "acme-prod")

    def test_team_is_required(self):
        # A connection without a team can never be scanned (the VERCEL_TEAM consent pin).
        req = CreateVercelConnectionRequest.from_payload({"token": "vc_tok"})
        assert "team" in (req.validation_error() or "")

    @pytest.mark.parametrize("team", ["Acme", "acme team", "team_", "$(evil)", "a;b"])
    def test_malformed_team_is_rejected(self, team):
        req = CreateVercelConnectionRequest.from_payload({"team": team, "token": "vc_tok"})
        assert req.validation_error() is not None

    def test_token_is_required(self):
        req = CreateVercelConnectionRequest.from_payload({"team": "acme"})
        assert "token" in (req.validation_error() or "")


class TestUpdateVercelConnectionRequest:
    def test_partial_update_leaves_omitted_fields_none(self):
        req = UpdateVercelConnectionRequest.from_payload({"name": "Renamed"})
        assert req.validation_error() is None
        assert req.name == "Renamed"
        assert req.team is None and req.token is None and req.status is None
        assert req.team_parts is None

    def test_status_only_connected_or_disabled(self):
        assert UpdateVercelConnectionRequest.from_payload({"status": "disabled"}).validation_error() is None
        assert UpdateVercelConnectionRequest.from_payload({"status": "error"}).validation_error() is not None

    def test_team_cannot_be_cleared(self):
        req = UpdateVercelConnectionRequest.from_payload({"team": ""})
        assert req.validation_error() is not None
