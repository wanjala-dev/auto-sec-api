"""The run row and the tool gate resolve the SAME mode (ADR 0035 D5).

This is the file the shared resolver exists for. Before it, the gate resolved
the workspace mode itself and the run row was not written at all; finishing D5
meant adding a second place that answers "what autonomy is this?", and
``_stamp_autonomy_mode`` already warns exactly what that costs:

    "a second resolution site could disagree with the gate, and then the audit
     trail would describe a policy that was never applied."

A trail that describes an unapplied policy is worse than no trail, because it is
believed. So both callers now go through ``resolve_run_mode``, and this pins the
agreement across the whole input matrix rather than trusting that they share a
function today and will still share it after the next edit.

**One honest limitation, stated rather than hidden.** The runner resolves at run
start; the gate resolves at the first tool call and caches for the run (D1). If
an operator changes the setting in the seconds between, the row records the
start value and the gate enforces the first-call value. Closing that would mean
the gate trusting a mode handed to it — and on the paths where ``agent_config``
originates from request data, that would let a client nominate its own autonomy
mode. A resolved-server-side answer with a seconds-wide window beats a spoofable
one with none.
"""

from __future__ import annotations

import pytest

from components.agents.domain.value_objects.autonomy_mode import AutonomyMode
from components.agents.infrastructure.adapters.langchain.autonomy_resolution import (
    read_workspace_mode,
    resolve_run_mode,
)
from components.agents.infrastructure.adapters.langchain.base import (
    _stamp_autonomy_mode,
    _workspace_autonomy_mode,
)
from components.workspace.application.providers.workspace_autonomy_provider import (
    WorkspaceAutonomyProvider,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class _Agent:
    def __init__(self, workspace_id, user_id, config=None):
        self.workspace_id = str(workspace_id)
        self.user_id = str(user_id) if user_id else None
        self.config = config or {}


def _set_mode(workspace, mode):
    WorkspaceAutonomyProvider.build_set_workspace_autonomy_mode_use_case().execute(
        workspace_id=str(workspace.id), mode=mode, actor=None, reason="test"
    )


def _gate_mode(agent):
    """What the ENFORCEMENT side concludes, via the path ``_risk_gated`` uses."""
    from components.agents.infrastructure.adapters.langchain.base import is_ai_service_principal

    _stamp_autonomy_mode(
        agent,
        execution_mode=agent.config.get("execution_mode"),
        is_autonomous=is_ai_service_principal(agent.user_id, agent.workspace_id),
        workspace_mode=_workspace_autonomy_mode(agent),
    )
    return agent._autonomy_mode


def _run_mode(agent):
    """What the RECORDING side concludes, via the path the runner uses."""
    return resolve_run_mode(
        execution_mode=agent.config.get("execution_mode"),
        user_id=agent.user_id,
        workspace_id=agent.workspace_id,
    ).value


class TestTheTwoSitesAgree:
    @pytest.mark.parametrize("workspace_mode", ["manual", "assist", "autonomous"])
    @pytest.mark.parametrize("execution_mode", [None, "evaluation"])
    def test_across_every_setting_and_execution_mode(
        self, workspace_factory, user_factory, workspace_mode, execution_mode
    ):
        workspace, user = workspace_factory(), user_factory()
        _set_mode(workspace, workspace_mode)
        agent = _Agent(workspace.id, user.id, {"execution_mode": execution_mode})

        assert _gate_mode(agent) == _run_mode(agent)

    def test_they_agree_that_an_unreadable_setting_is_unknown(self, workspace_factory, user_factory, monkeypatch):
        """The branch most likely to drift, because nothing exercises it in
        normal operation — and the one where disagreement is worst: the gate
        would hold writes while the row claimed ASSIST."""
        import components.agents.infrastructure.adapters.workspace_autonomy_adapter as adapter_module

        def _explode(self, *, workspace_id):
            raise RuntimeError("settings read failed")

        monkeypatch.setattr(adapter_module.WorkspaceAutonomyAdapter, "get_mode", _explode)

        agent = _Agent(workspace_factory().id, user_factory().id)

        assert _gate_mode(agent) == _run_mode(agent) == AutonomyMode.UNKNOWN.value


class TestTheSharedReader:
    def test_a_missing_workspace_is_none_not_unknown(self):
        """ "Nothing to govern" and "we could not read the policy" must stay
        distinguishable: one is a run with no tenant, the other holds writes."""
        assert read_workspace_mode(None) is None
        assert read_workspace_mode("") is None

    def test_an_absent_workspace_row_is_none(self):
        assert read_workspace_mode("00000000-0000-0000-0000-000000000000") is None

    def test_a_stored_mode_comes_back_parsed(self, workspace_factory):
        workspace = workspace_factory()
        _set_mode(workspace, "manual")

        assert read_workspace_mode(str(workspace.id)) is AutonomyMode.MANUAL

    def test_a_failed_read_is_unknown_rather_than_raising(self, workspace_factory, monkeypatch):
        """A governance read must never be the thing that takes a run down; an
        uninterpretable answer IS a mode we do not know."""
        import components.agents.infrastructure.adapters.workspace_autonomy_adapter as adapter_module

        def _explode(self, *, workspace_id):
            raise RuntimeError("boom")

        monkeypatch.setattr(adapter_module.WorkspaceAutonomyAdapter, "get_mode", _explode)

        assert read_workspace_mode(str(workspace_factory().id)) is AutonomyMode.UNKNOWN

    def test_an_uninterpretable_stored_value_is_unknown(self, workspace_factory):
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = workspace_factory()
        Workspace.objects.filter(id=workspace.id).update(autonomy_mode="something-else")

        assert read_workspace_mode(str(workspace.id)) is AutonomyMode.UNKNOWN
