"""The immediate-dispatch half: a finding must not wait for the next cadence tick.

Covers the three triggers that share ONE engine — on-detection, cadence, on-demand —
and the properties that keep "immediate" from meaning "unbounded": the shared lease
collapses a burst, the gates the cadence honours are honoured here too, and the
cadence remains a correct backstop on its own.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.agents.application.ports.finding_dispatch_port import DraftFixRefused
from components.agents.infrastructure.services import finding_dispatch_service as fds

pytestmark = pytest.mark.unit

_DISPATCH_TASK = "components.agents.infrastructure.tasks.agent_tasks.dispatch_finding_specialist"
_DRAFT_FIX_TASK = "components.agents.infrastructure.tasks.agent_tasks.draft_fix_for_finding"
_WS = "ws-1"


def _immediate(**kw):
    """Run the on-detection request with commit hooks fired inline and gates open."""
    defaults = {
        "source_type": "ai.code_security",
        "trigger": "finding_raised",
    }
    defaults.update(kw)
    return fds.request_specialist_dispatch(_WS, defaults.pop("specialist", "code_security_agent"), **defaults)


def test_immediate_dispatch_enqueues_on_detection():
    """The whole point: a raised finding dispatches its specialist NOW."""
    with (
        mock.patch(_DISPATCH_TASK) as dispatch,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=True),
        mock.patch("django.core.cache.cache.add", return_value=True),
        mock.patch("django.db.transaction.on_commit", side_effect=lambda cb: cb()),
    ):
        assert _immediate() is True
        dispatch.apply_async.assert_called_once()
        kwargs = dispatch.apply_async.call_args.kwargs
        args = kwargs["args"]
        assert args[0] == _WS
        assert args[1] == "code_security_agent"
        # Pinned worker + deep mode: a known target must never be re-routed by the
        # planner (the documented mis-route-and-fabricate failure).
        assert args[3]["worker_agent_type"] == "code_security_agent"
        assert args[3]["mode"] == "deep"
        # Debounced, not instant: a scan files its cards one event-task at a time,
        # so the run must not start on the first card and see a batch of one.
        assert kwargs["countdown"] == fds.IMMEDIATE_DEBOUNCE_SECONDS


def test_a_burst_of_findings_collapses_to_one_dispatch():
    """A 500-finding scan must not fan out 500 deep runs.

    The shared per-(workspace, specialist) lease is what bounds it: the first card
    claims it, every later card in the same scan is a no-op.
    """
    calls = {"n": 0}

    def fake_add(key, value, ttl):  # first caller wins, like cache.add
        calls["n"] += 1
        return calls["n"] == 1

    with (
        mock.patch(_DISPATCH_TASK) as dispatch,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=True),
        mock.patch("django.core.cache.cache.add", side_effect=fake_add),
        mock.patch("django.db.transaction.on_commit", side_effect=lambda cb: cb()),
    ):
        results = [_immediate() for _ in range(500)]

    assert results[0] is True
    assert not any(results[1:])
    assert dispatch.apply_async.call_count == 1


def test_cadence_and_immediate_contend_for_the_same_lease():
    """The immediate path and the backstop cadence can never double-fire."""
    assert fds.dispatch_lease_key(_WS, "triage_agent") == "ai_finding_router:dispatch:ws-1:triage_agent"


def test_non_routable_finding_never_dispatches():
    """Operator-reading findings (cloud posture, planted instructions) are not dispatched."""
    with mock.patch(_DISPATCH_TASK) as dispatch, mock.patch("django.core.cache.cache.add") as cache_add:
        assert _immediate(source_type="ai.cloud_posture", specialist="triage_agent") is False
        assert _immediate(source_type="ai.code_security", specialist="ai_teammate") is False
        dispatch.apply_async.assert_not_called()
        # Cheap by construction: a non-routable card costs no cache op and no query,
        # so this runs per raised finding without cost.
        cache_add.assert_not_called()


def test_immediate_dispatch_respects_workspace_ai_toggle_and_kill_switch():
    """Immediate must not reach further than the cadence could.

    ``ai_teammate_enabled`` gates the beat fan-out; the kill switch halts the
    detector cycle. This path bypasses both mechanisms, so it checks them itself.
    """
    with (
        mock.patch(_DISPATCH_TASK) as dispatch,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=False),
        mock.patch("django.core.cache.cache.add", return_value=True) as cache_add,
    ):
        assert _immediate() is False
        dispatch.apply_async.assert_not_called()
        cache_add.assert_not_called()  # gate is checked BEFORE the lease is burned


def test_ai_dispatch_allowed_is_fail_safe():
    """A gate lookup error degrades to "do not dispatch" — worst case is today's
    behaviour (the cadence picks it up), never an unbudgeted fan-out of deep runs."""
    with mock.patch("infrastructure.persistence.workspaces.models.Workspace") as ws_model:
        ws_model.objects.all_objects.side_effect = RuntimeError("db down")
        assert fds.ai_dispatch_allowed(_WS) is False


def test_ai_dispatch_allowed_false_when_workspace_toggle_off():
    with mock.patch("infrastructure.persistence.workspaces.models.Workspace") as ws_model:
        ws_model.objects.all_objects.return_value.filter.return_value.values_list.return_value.first.return_value = (
            False
        )
        assert fds.ai_dispatch_allowed(_WS) is False


def test_ai_dispatch_allowed_false_when_kill_switch_tripped():
    with (
        mock.patch("infrastructure.persistence.workspaces.models.Workspace") as ws_model,
        mock.patch("components.agents.application.policies.ai_kill_switch.is_ai_killed", return_value=True),
    ):
        ws_model.objects.all_objects.return_value.filter.return_value.values_list.return_value.first.return_value = True
        assert fds.ai_dispatch_allowed(_WS) is False


# ── On-demand: the operator's "draft a fix PR" button ────────────────────


def _card(metadata=None, source_type="ai.code_security"):
    card = mock.Mock()
    card.source_type = source_type
    card.metadata = metadata if metadata is not None else {"agent_type": "code_security_agent"}
    return card


def _patch_card(card):
    return mock.patch(
        "infrastructure.persistence.project.models.Task.objects.filter",
        return_value=mock.Mock(only=mock.Mock(return_value=mock.Mock(first=mock.Mock(return_value=card)))),
    )


def test_draft_fix_enqueues_and_never_runs_the_pipeline_inline():
    """The endpoint must return immediately — the deep pipeline is 10–30s of LLM
    calls and blocking the request thread on it is the standing problem this must
    not extend."""
    with (
        _patch_card(_card()),
        mock.patch(_DRAFT_FIX_TASK) as task,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=True),
        mock.patch.object(fds, "stamp_dispatch_in_flight", return_value=1) as stamp,
        mock.patch("django.core.cache.cache.add", return_value=True),
        mock.patch("django.db.transaction.on_commit", side_effect=lambda cb: cb()),
    ):
        result = fds.request_draft_fix(_WS, "42", performed_by="user-1")

    assert result["state"] == "drafting"
    assert result["already_in_flight"] is False
    task.delay.assert_called_once_with(_WS, "42", "user-1")
    # The card flips to DRAFTING immediately so the click is never a dead click.
    stamp.assert_called_once()


def test_draft_fix_double_click_is_idempotent():
    """A second click while a run is in flight reports DRAFTING, not an error —
    the operator sees the same honest state either way."""
    with (
        _patch_card(_card()),
        mock.patch(_DRAFT_FIX_TASK) as task,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=True),
        mock.patch.object(fds, "stamp_dispatch_in_flight", return_value=1),
        mock.patch("django.core.cache.cache.add", return_value=False),  # lease already held
    ):
        result = fds.request_draft_fix(_WS, "42", performed_by="user-1")

    assert result == {"state": "drafting", "already_in_flight": True}
    task.delay.assert_not_called()


def test_draft_fix_lease_is_per_finding_not_per_specialist():
    """Keyed per finding so an unrelated background dispatch cannot make the button
    silently no-op — a dead click is exactly the confusion this work removes."""
    a = fds.draft_fix_lease_key(_WS, "42")
    b = fds.draft_fix_lease_key(_WS, "43")
    assert a != b
    assert a != fds.dispatch_lease_key(_WS, "code_security_agent")


@pytest.mark.parametrize(
    ("card", "expected_reason"),
    [
        (None, "finding_not_found"),
        (_card(source_type="ai.cloud_posture"), "not_routable"),
        (_card(metadata={"agent_type": "ai_teammate"}), "not_routable"),
        (
            _card(
                metadata={
                    "agent_type": "code_security_agent",
                    "payload": {"draft_pr": {"url": "https://github.com/o/r/pull/1"}},
                }
            ),
            "draft_pr_exists",
        ),
    ],
)
def test_draft_fix_refuses_with_a_reason(card, expected_reason):
    """An operator always gets a machine-readable reason, never a dead click."""
    with (
        _patch_card(card),
        mock.patch(_DRAFT_FIX_TASK) as task,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=True),
        pytest.raises(DraftFixRefused) as exc,
    ):
        fds.request_draft_fix(_WS, "42", performed_by="user-1")
    assert exc.value.reason == expected_reason
    task.delay.assert_not_called()


def test_draft_fix_refused_when_ai_is_off():
    with (
        _patch_card(_card()),
        mock.patch(_DRAFT_FIX_TASK) as task,
        mock.patch.object(fds, "ai_dispatch_allowed", return_value=False),
        pytest.raises(DraftFixRefused) as exc,
    ):
        fds.request_draft_fix(_WS, "42", performed_by="user-1")
    assert exc.value.reason == "ai_unavailable"
    task.delay.assert_not_called()


def test_finding_goal_names_the_exact_finding():
    """A single-finding run must not have to guess which finding it is for — the
    specialist's triage tool is driven by the goal text."""
    goal = fds.build_finding_goal("42", {"payload": {"path": "app/x.py", "start_line": 9, "repo": "org/repo"}})
    assert '{"task_id": "42"}' in goal
    assert "org/repo" in goal and "app/x.py:9" in goal
    assert "Do not triage any other finding" in goal
