"""Unit tests: TrashWorkspaceLoginActivityUseCase (T2-S4).

Pure fakes, no DB. Covers the happy path (exclusion created + one bin
entry recorded), idempotency (already hidden → same exclusion id, no
second bin entry), and the not-a-member guard (404-shaped domain error,
nothing written).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.identity.application.policies.org_audit_visibility_policy import OrgAuditVisibilityPolicy
from components.identity.application.use_cases.trash_workspace_login_activity_use_case import (
    LOGIN_ACTIVITY_ENTITY_TYPE,
    TrashWorkspaceLoginActivityUseCase,
)
from components.identity.domain.errors import LoginActivityEventNotFoundError, OrgAuditLogDisabledError


class FakeActivityPort:
    """Only the method the use case touches — workspace event lookup."""

    def __init__(self, events=None):
        # {(workspace_id, event_id): sentinel-event}
        self._events = dict(events or {})

    def get_workspace_event(self, *, workspace_id, event_id):
        return self._events.get((workspace_id, event_id))


class FakeExclusionPort:
    def __init__(self):
        self.rows = {}  # (workspace_id, event_id) -> exclusion UUID

    def get_or_create(self, *, workspace_id, event_id, hidden_by):
        key = (workspace_id, event_id)
        if key in self.rows:
            return self.rows[key], False
        exclusion_id = uuid4()
        self.rows[key] = exclusion_id
        return exclusion_id, True


class FakeRecycleBin:
    def __init__(self):
        self.trashed = []

    def trash(self, command):
        self.trashed.append(command)
        return command


class FakeOrgAuditLogSettings:
    """In-memory OrgAuditLogSettingsPort — default ON, like production."""

    def __init__(self, enabled=True):
        self.enabled = enabled

    def is_enabled(self, workspace_id):
        return self.enabled

    def set_enabled(self, workspace_id, enabled):
        self.enabled = bool(enabled)
        return self.enabled


def _build(events=None, *, audit_log_enabled=True):
    activity = FakeActivityPort(events)
    exclusions = FakeExclusionPort()
    recycle_bin = FakeRecycleBin()
    use_case = TrashWorkspaceLoginActivityUseCase(
        activity_port=activity,
        exclusion_port=exclusions,
        recycle_bin=recycle_bin,
        visibility_policy=OrgAuditVisibilityPolicy(settings_port=FakeOrgAuditLogSettings(enabled=audit_log_enabled)),
    )
    return use_case, exclusions, recycle_bin


class TestTrashWorkspaceLoginActivityUseCase:
    def test_happy_path_creates_exclusion_and_records_bin_entry(self):
        # AuthAuditEvent uses an integer PK — event ids are ints.
        workspace_id, event_id, admin_id = uuid4(), 101, uuid4()
        use_case, exclusions, recycle_bin = _build({(workspace_id, event_id): object()})

        exclusion_id = use_case.execute(workspace_id=workspace_id, event_id=event_id, deleted_by=admin_id)

        assert exclusions.rows[(workspace_id, event_id)] == exclusion_id
        (command,) = recycle_bin.trashed
        assert command.entity_type == LOGIN_ACTIVITY_ENTITY_TYPE
        assert command.entity_id == str(exclusion_id)
        assert command.workspace_id == workspace_id
        assert command.deleted_by == admin_id

    def test_already_hidden_event_is_idempotent(self):
        workspace_id, event_id, admin_id = uuid4(), 202, uuid4()
        use_case, _exclusions, recycle_bin = _build({(workspace_id, event_id): object()})

        first = use_case.execute(workspace_id=workspace_id, event_id=event_id, deleted_by=admin_id)
        second = use_case.execute(workspace_id=workspace_id, event_id=event_id, deleted_by=admin_id)

        assert first == second
        assert len(recycle_bin.trashed) == 1  # no duplicate bin entry

    def test_event_not_in_workspace_raises_not_found_and_writes_nothing(self):
        use_case, exclusions, recycle_bin = _build()  # no events at all

        with pytest.raises(LoginActivityEventNotFoundError):
            use_case.execute(workspace_id=uuid4(), event_id=303, deleted_by=uuid4())

        assert exclusions.rows == {}
        assert recycle_bin.trashed == []

    def test_toggle_off_raises_disabled_before_any_write(self):
        workspace_id, event_id, admin_id = uuid4(), 404, uuid4()
        use_case, exclusions, recycle_bin = _build({(workspace_id, event_id): object()}, audit_log_enabled=False)

        with pytest.raises(OrgAuditLogDisabledError):
            use_case.execute(workspace_id=workspace_id, event_id=event_id, deleted_by=admin_id)

        assert exclusions.rows == {}
        assert recycle_bin.trashed == []
