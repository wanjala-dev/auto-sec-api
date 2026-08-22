"""Only an AUTONOMOUS workspace is started by the scheduler (ADR 0035 D2/D7).

Before this, `Workspace.autonomy_mode` was a stored value nothing read on the
scheduling side: eligibility for unattended runs came from `ai_teammate_enabled`
alone. So the third dial position did nothing, and — worse — a workspace could
be receiving teammate cycles every five minutes while its dial displayed ASSIST.

The cause is that the kill switch was doing two jobs at once. D7 says it is a
power control ("nothing runs at all"); it was also acting as the policy control
("may run unattended"), which is AUTONOMOUS's job. These pin the two apart:

    ai_teammate_enabled  →  may anything run?        (D7, power)
    autonomy_mode        →  may it start by itself?  (D2, policy)

Both must be satisfied. Testing `iter_enabled_seeds` directly is deliberate —
it is the query the fan-out iterates, so a workspace appearing here is a
workspace the scheduler will dispatch a cycle for.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.services.actions_service import get_ai_action_service
from infrastructure.persistence.ai.models import AITeammateProfile

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _teammate(workspace, user, *, enabled=True):
    return AITeammateProfile.objects.create(
        workspace=workspace,
        user=user,
        is_enabled=enabled,
        status=AITeammateProfile.STATUS_ACTIVE,
    )


def _workspace(workspace_factory, *, ai_enabled=True, mode="assist"):
    from infrastructure.persistence.workspaces.models import Workspace

    workspace = workspace_factory()
    Workspace.objects.filter(id=workspace.id).update(ai_teammate_enabled=ai_enabled, autonomy_mode=mode)
    return workspace


def _eligible_ids():
    return {str(p.workspace_id) for p in get_ai_action_service().iter_enabled_seeds()}


class TestOnlyAutonomousRunsUnattended:
    def test_an_autonomous_workspace_is_scheduled(self, workspace_factory, user_factory):
        workspace = _workspace(workspace_factory, mode="autonomous")
        _teammate(workspace, user_factory())

        assert str(workspace.id) in _eligible_ids()

    @pytest.mark.parametrize("mode", ["assist", "manual"])
    def test_assist_and_manual_are_not_scheduled(self, workspace_factory, user_factory, mode):
        """The whole point. A workspace on ASSIST is started by a human or an
        event — never by the scheduler with nobody watching."""
        workspace = _workspace(workspace_factory, mode=mode)
        _teammate(workspace, user_factory())

        assert str(workspace.id) not in _eligible_ids()

    def test_an_uninterpretable_mode_is_not_scheduled(self, workspace_factory, user_factory):
        """Fails closed. If we cannot tell what a customer chose, we do not
        start runs in their account on our own initiative."""
        workspace = _workspace(workspace_factory, mode="something-else")
        _teammate(workspace, user_factory())

        assert str(workspace.id) not in _eligible_ids()


class TestTheKillSwitchStillWinsOutright:
    def test_the_switch_off_beats_autonomous(self, workspace_factory, user_factory):
        """D7 — OFF means nothing runs at all, by any trigger. It is a power
        control, not a fourth position on the dial, so the most permissive mode
        must not be able to talk past it."""
        workspace = _workspace(workspace_factory, ai_enabled=False, mode="autonomous")
        _teammate(workspace, user_factory())

        assert str(workspace.id) not in _eligible_ids()

    def test_a_disabled_teammate_is_not_scheduled(self, workspace_factory, user_factory):
        workspace = _workspace(workspace_factory, mode="autonomous")
        _teammate(workspace, user_factory(), enabled=False)

        assert str(workspace.id) not in _eligible_ids()

    def test_both_gates_are_required_not_either(self, workspace_factory, user_factory):
        """Guards against the filter degrading into an OR, which would restore
        the old behaviour while looking like it had been fixed."""
        both = _workspace(workspace_factory, ai_enabled=True, mode="autonomous")
        power_only = _workspace(workspace_factory, ai_enabled=True, mode="assist")
        policy_only = _workspace(workspace_factory, ai_enabled=False, mode="autonomous")
        neither = _workspace(workspace_factory, ai_enabled=False, mode="assist")
        for workspace in (both, power_only, policy_only, neither):
            _teammate(workspace, user_factory())

        eligible = _eligible_ids()

        assert str(both.id) in eligible
        assert eligible.isdisjoint({str(power_only.id), str(policy_only.id), str(neither.id)})


class TestSelectingAutonomousChangesSomething:
    def test_flipping_the_dial_moves_a_workspace_in_and_out_of_scheduling(self, workspace_factory, user_factory):
        """The end-to-end claim the mode picker makes to an operator: choosing
        AUTONOMOUS has an effect, and choosing ASSIST takes it away. Driven
        through the real use case, not a direct column write."""
        from components.workspace.application.providers.workspace_autonomy_provider import (
            WorkspaceAutonomyProvider,
        )

        workspace = _workspace(workspace_factory, mode="assist")
        _teammate(workspace, user_factory())
        set_mode = WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case()

        assert str(workspace.id) not in _eligible_ids()

        set_mode.execute(workspace_id=str(workspace.id), mode="autonomous", actor=None, reason="t")
        assert str(workspace.id) in _eligible_ids()

        set_mode.execute(workspace_id=str(workspace.id), mode="assist", actor=None, reason="t")
        assert str(workspace.id) not in _eligible_ids()


class TestTheCatalogDescribesTheNewBehaviour:
    def test_autonomous_says_it_starts_its_own_runs(self):
        """The copy an operator reads before flipping the switch has to match
        what the switch now does, or the UI is the thing that is lying."""
        from components.agents.application.services import autonomy_mode_service

        catalog = {m["mode"]: m for m in autonomy_mode_service.catalog()}

        assert "starts its own runs" in catalog["autonomous"]["summary"]
        assert "never the scheduler" in catalog["assist"]["initiated_by"]

    def test_autonomous_still_advertises_no_extra_permission(self):
        """D3 is untouched by this change and must stay visibly untouched."""
        from components.agents.application.services import autonomy_mode_service

        catalog = {m["mode"]: m for m in autonomy_mode_service.catalog()}
        assist = {r["risk"]: r["decision"] for r in catalog["assist"]["permissions"]}

        for row in catalog["autonomous"]["permissions"]:
            if row["decision"] == "execute":
                assert assist[row["risk"]] == "execute"
