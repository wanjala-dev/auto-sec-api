"""The workspace setting, end to end (ADR 0035 D6/D8).

The point of these is that the switch is not a decoration. A mode selector that
stores a value nothing reads is the defect this repo has shipped before — a
control that looks like governance and enforces nothing. So these assert the
round trip: set it, read it back through the seam the tool gate actually uses,
and confirm the audit exists.
"""

from __future__ import annotations

import pytest

from components.agents.application.services import autonomy_mode_service
from components.agents.infrastructure.adapters.workspace_autonomy_adapter import (
    WorkspaceAutonomyAdapter,
)
from components.shared_kernel.domain.errors import NotFoundError, ValidationError
from components.workspace.application.providers.workspace_autonomy_provider import (
    WorkspaceAutonomyProvider,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _set(workspace, mode, actor=None, reason="test"):
    return WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case().execute(
        workspace_id=str(workspace.id), mode=mode, actor=actor, reason=reason
    )


class TestTheDefaultIsTodaysBehaviour:
    def test_a_new_workspace_is_on_assist(self, workspace_factory):
        """Nobody's agent behaviour changes on deploy. If this ever failed,
        shipping the field would itself be a behaviour change."""
        workspace = workspace_factory()

        assert autonomy_mode_service.status(str(workspace.id))["mode"] == "assist"


class TestTheSettingRoundTrips:
    @pytest.mark.parametrize("mode", ["manual", "assist", "autonomous"])
    def test_what_is_set_is_what_the_gate_reads(self, workspace_factory, mode):
        """Through the adapter the tool gate uses — not by re-reading the model.
        A test that checks the write with the writer's own query proves the ORM
        works, not that enforcement sees it."""
        workspace = workspace_factory()

        _set(workspace, mode)

        assert WorkspaceAutonomyAdapter().get_mode(workspace_id=str(workspace.id)) == mode

    def test_it_reports_what_changed(self, workspace_factory):
        workspace = workspace_factory()

        result = _set(workspace, "manual")

        assert (result.previous, result.current, result.changed) == ("assist", "manual", True)

    def test_setting_the_same_mode_twice_is_not_a_change(self, workspace_factory):
        """So a repeat request never fabricates a second entry in the trail —
        "the mode was changed" must mean it was."""
        workspace = workspace_factory()
        _set(workspace, "manual")

        assert _set(workspace, "manual").changed is False

    def test_case_and_padding_are_tolerated(self, workspace_factory):
        workspace = workspace_factory()

        assert _set(workspace, "  MANUAL ").current == "manual"


class TestItRefusesWhatItCannotEnforce:
    @pytest.mark.parametrize("mode", ["", "evaluation", "unknown", "off", "yolo"])
    def test_an_unselectable_mode_is_rejected(self, workspace_factory, mode):
        """EVALUATION and UNKNOWN are real modes but not settings: one is
        imposed by the eval harness for the length of a run, the other is the
        absence of a value. Storing either would leave the gate enforcing a
        policy no operator chose."""
        workspace = workspace_factory()

        with pytest.raises(ValidationError):
            _set(workspace, mode)

    def test_the_stored_value_survives_a_rejected_change(self, workspace_factory):
        workspace = workspace_factory()
        _set(workspace, "manual")

        with pytest.raises(ValidationError):
            _set(workspace, "nonsense")

        assert WorkspaceAutonomyAdapter().get_mode(workspace_id=str(workspace.id)) == "manual"

    def test_an_unknown_workspace_is_not_found(self, workspace_factory):
        use_case = WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case()

        with pytest.raises(NotFoundError):
            use_case.execute(workspace_id="00000000-0000-0000-0000-000000000000", mode="manual", actor=None, reason="")


class TestTheChangeIsAudited:
    def test_a_mode_change_writes_a_field_change_entry(self, workspace_factory, user_factory):
        """D8 — the highest-consequence setting in the product, and the first
        thing an incident review asks about. An unaudited change to it is a
        governance hole, not a missing nicety."""
        from infrastructure.persistence.audit.models import EntityAuditLog

        workspace, actor = workspace_factory(), user_factory()

        _set(workspace, "autonomous", actor=actor, reason="scheduled sweeps approved")

        assert EntityAuditLog.objects.filter(object_id=str(workspace.id), field_name="autonomy_mode").exists()


class TestTheCatalogDescribesTheRealPolicy:
    def test_it_offers_exactly_the_selectable_modes(self):
        assert [m["mode"] for m in autonomy_mode_service.catalog()] == ["manual", "assist", "autonomous"]

    def test_manual_proposes_writes_rather_than_running_them(self):
        manual = next(m for m in autonomy_mode_service.catalog() if m["mode"] == "manual")
        by_risk = {row["risk"]: row["decision"] for row in manual["permissions"]}

        assert by_risk["read"] == "execute"
        assert by_risk["reversible_write"] == "hold"

    def test_autonomous_is_not_advertised_as_permitting_more_than_assist(self):
        """The catalog is what a customer reads before flipping the switch. If
        it ever promised AUTONOMOUS could do more, we would be selling D3 away
        in the UI copy."""
        catalog = {m["mode"]: m for m in autonomy_mode_service.catalog()}
        assist = {r["risk"]: r["decision"] for r in catalog["assist"]["permissions"]}
        autonomous = {r["risk"]: r["decision"] for r in catalog["autonomous"]["permissions"]}

        for risk, decision in autonomous.items():
            if decision == "execute":
                assert assist[risk] == "execute", f"catalog claims AUTONOMOUS widens {risk}"


class TestUnknownIsNotPreSelected:
    def test_an_uninterpretable_stored_value_reads_as_unrecorded(self, workspace_factory):
        """Rather than quietly showing ASSIST. The operator should see that the
        setting needs attention, not a mode they never chose."""
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = workspace_factory()
        Workspace.objects.filter(id=workspace.id).update(autonomy_mode="something-else")

        payload = autonomy_mode_service.status(str(workspace.id))

        assert payload["mode"] == "unknown"
        assert payload["is_recorded"] is False
