"""SEE-202 — emergency AI kill switch.

The switch must be off by default, halt every workspace when tripped globally,
halt only the targeted workspace when tripped workspace-scoped, and cause the
AI service methods to refuse (503-mapped ``AiUnavailable``).

Uses bare workspace-id strings rather than ``workspace_factory`` — ``is_ai_killed``
resolves feature-flag rules by id and never loads the Workspace row, so a real
workspace (and its embedding-reindex side effects) is unnecessary.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.agents.application.policies.ai_kill_switch import (
    KILL_SWITCH_FLAG,
    is_ai_killed,
)
from components.agents.application.service import AgentsService
from components.agents.domain.errors import AiUnavailable
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule


@pytest.fixture(autouse=True)
def _clear_flag_cache():
    # The feature-flag cache is process-global and is NOT rolled back by
    # django_db, so a prior test's trip would leak into this one. Clear it
    # around each test (production invalidates via bump_feature_flags_version).
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _trip(*, scope, workspace_id=None):
    flag, _ = FeatureFlag.objects.get_or_create(key=KILL_SWITCH_FLAG, defaults={"default_enabled": False})
    FeatureFlagRule.objects.create(flag=flag, scope=scope, workspace_id=workspace_id, enabled=True)
    bump_feature_flags_version()


@pytest.mark.django_db
class TestAiKillSwitch:
    def test_off_by_default(self):
        assert is_ai_killed(str(uuid4())) is False

    def test_global_trip_halts_all_workspaces(self):
        ws = str(uuid4())

        _trip(scope=FeatureFlagRule.Scope.GLOBAL)

        assert is_ai_killed(ws) is True

    def test_workspace_scoped_trip_halts_only_that_workspace(self, workspace_factory):
        # A WORKSPACE-scoped FeatureFlagRule FKs to a real Workspace row.
        target = workspace_factory()
        other = workspace_factory()

        _trip(scope=FeatureFlagRule.Scope.WORKSPACE, workspace_id=str(target.id))

        assert is_ai_killed(str(target.id)) is True
        assert is_ai_killed(str(other.id)) is False

    def test_none_workspace_is_not_killed(self):
        assert is_ai_killed(None) is False


@pytest.mark.django_db
class TestServiceGuard:
    def test_service_guard_raises_when_killed(self):
        _trip(scope=FeatureFlagRule.Scope.GLOBAL)

        with pytest.raises(AiUnavailable):
            AgentsService._raise_if_ai_killed(str(uuid4()))

    def test_service_guard_is_noop_when_available(self):
        # Does not raise.
        AgentsService._raise_if_ai_killed(str(uuid4()))
