"""Fitness functions for the scanner-pillar registration lists (audit R5).

Adding a scanning pillar means touching a dozen hand-maintained lists (the
scanner registry, the board's ``_SOURCE_BOARD``, the queue guards, the per-env
beat schedules, …). Each list is fine as an explicit registration point — what
is NOT fine is the lists drifting apart silently: at three pillars this repo
had already drifted twice (the queue-guard sets were missing ``code_security``
while the deployed scanning-worker consumed it, and dev/prod beat schedules
silently lacked two pillars). These tests turn "drifts silently at pillar N"
into "CI fails at pillar 4" — the same anti-strand pattern as
``components/agents/tests/unit/test_finding_routing_contract.py`` (#276),
generalized to the registration lists.

Ground truth for the consumed-queue set stays ``tests/test_celery_task_routes.py``
(the auto-sec-infra worker ``-Q`` args); this file asserts the OTHER lists agree
with the registry instead of duplicating that truth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from components.scanning.application.providers.scanner_registry import _REGISTRY
from tests.test_celery_task_routes import CONSUMED_QUEUES, DISPATCH_PINNED_QUEUES

pytestmark = pytest.mark.unit

_SETTINGS_DIR = Path(__file__).resolve().parent.parent / "api" / "settings"


def test_every_registered_scanner_source_has_a_board_mapping():
    """A registry entry without a ``_SOURCE_BOARD`` mapping scans into the void.

    The spine emits ``FindingObserved`` → SSOT → ``FindingRaised`` → the board
    handler, which drops any source it has no mapping for. A pillar registered
    for execution but absent from the board map produces findings no operator
    ever sees — the silent-strand failure mode, one hop earlier than #276's.
    """
    from components.agents.application.handlers.finding_raised_board_handler import _SOURCE_BOARD

    missing = sorted(set(_REGISTRY) - set(_SOURCE_BOARD))
    assert not missing, (
        f"Scanner sources registered for execution but with NO board mapping {missing} — "
        "their findings reach the SSOT but never surface on the board. Add a "
        "_SOURCE_BOARD entry (and card builder) for each, or deliberately document why not."
    )


def test_every_registry_queue_has_a_deployed_consumer():
    """A registry queue no deployed worker consumes is a task black hole."""
    registry_queues = {entry.queue for entry in _REGISTRY.values()}
    unconsumed = sorted(registry_queues - CONSUMED_QUEUES)
    assert not unconsumed, (
        f"Scanner registry pins queues {unconsumed} that no deployed k8s worker consumes "
        "(ground truth: CONSUMED_QUEUES in tests/test_celery_task_routes.py, from the "
        "auto-sec-infra worker -Q args). Ship a consuming worker + update that set."
    )


def test_dispatch_pinned_queue_guard_matches_the_registry():
    """``DISPATCH_PINNED_QUEUES`` documents every dynamic ``apply_async(queue=…)``
    dispatch site — today that is exactly the scanner registry. The guard drifted
    once already (``code_security`` was registered but missing from the set, so
    the newest pillar was silently un-guarded); equality makes the next pillar's
    registration fail this test until the guard list is consciously extended.
    """
    registry_queues = {entry.queue for entry in _REGISTRY.values()}
    assert registry_queues == DISPATCH_PINNED_QUEUES, (
        "The scanner registry's queues and DISPATCH_PINNED_QUEUES (tests/test_celery_task_routes.py) "
        f"disagree: registry={sorted(registry_queues)} guard={sorted(DISPATCH_PINNED_QUEUES)}. "
        "Update the guard set together with the registry — that is the whole point of the guard."
    )


# ── Beat-schedule presence per environment ───────────────────────────────────
#
# The CELERY_BEAT_SCHEDULE dict is repeated per settings file, and only *local*
# schedules the container_security / code_security pillars. That asymmetry is
# hereby DECIDED, not drifted (audit §2.2d): dev/prod deliberately keep the two
# newer engine pillars dark until their flags graduate — flipping one on in
# prod is a conscious edit to BOTH the settings file and this matrix, reviewed
# together. If you are adding pillar #4's beat entry, add it to this matrix in
# the same commit.
_EXPECTED_BEAT_TASKS: dict[str, dict[str, bool]] = {
    # task name → {settings module: expected present}
    "cloud_posture.schedule_prowler_runs": {"local": True, "dev": True, "prod": True},
    "cloud_posture.schedule_vercel_prowler_runs": {"local": True, "dev": True, "prod": True},
    "container_security.schedule_container_scans": {"local": True, "dev": False, "prod": False},
    "code_security.schedule_repo_scans": {"local": True, "dev": False, "prod": False},
}


def _beat_task_names(settings_module: str) -> set[str]:
    """Task names referenced in a settings file's text.

    Text-level on purpose: importing ``api.settings.prod`` in a test process
    would demand prod-only env (and its side effects). The ``"task": "…"``
    lines are a stable, greppable contract.
    """
    text = (_SETTINGS_DIR / f"{settings_module}.py").read_text()
    return set(re.findall(r"[\"']task[\"']\s*:\s*[\"']([\w.]+)[\"']", text))


@pytest.mark.parametrize("settings_module", ["local", "dev", "prod"])
def test_beat_schedule_presence_matches_the_decided_matrix(settings_module):
    present = _beat_task_names(settings_module)
    problems = []
    for task, expectations in _EXPECTED_BEAT_TASKS.items():
        expected = expectations[settings_module]
        if expected and task not in present:
            problems.append(f"{task} expected in api/settings/{settings_module}.py but is missing")
        if not expected and task in present:
            problems.append(
                f"{task} appeared in api/settings/{settings_module}.py but the decided matrix says dark — "
                "if that graduation is intentional, update _EXPECTED_BEAT_TASKS in the same commit"
            )
    assert not problems, "Beat-schedule drift (decide, don't drift):\n" + "\n".join(f"  - {p}" for p in problems)
