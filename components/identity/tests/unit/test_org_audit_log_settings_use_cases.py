"""Unit tests: org audit-log visibility policy + settings use cases.

Pure fakes, no DB. Covers:
- OrgAuditVisibilityPolicy — passes when enabled, raises the 403-shaped
  ``OrgAuditLogDisabledError`` (code ``org_audit_log_disabled``) when off.
- Get/Set settings use cases — read/flip through the port, defaults ON.
- The two org LIST use cases consult the policy before touching the
  activity port (the trash use case's guard is covered in its own file).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.identity.application.policies.org_audit_visibility_policy import OrgAuditVisibilityPolicy
from components.identity.application.queries.workspace_login_activity_query import WorkspaceLoginActivityQuery
from components.identity.application.use_cases.get_org_audit_log_settings_use_case import (
    GetOrgAuditLogSettingsUseCase,
)
from components.identity.application.use_cases.list_workspace_login_activity_use_case import (
    ListWorkspaceLoginActivityUseCase,
)
from components.identity.application.use_cases.list_workspace_sessions_use_case import (
    ListWorkspaceSessionsUseCase,
)
from components.identity.application.use_cases.set_org_audit_log_settings_use_case import (
    SetOrgAuditLogSettingsUseCase,
)
from components.identity.domain.errors import OrgAuditLogDisabledError


class FakeOrgAuditLogSettings:
    """In-memory OrgAuditLogSettingsPort — one fake for the whole port."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.set_calls = []

    def is_enabled(self, workspace_id):
        return self.enabled

    def set_enabled(self, workspace_id, enabled):
        self.set_calls.append((workspace_id, enabled))
        self.enabled = bool(enabled)
        return self.enabled


class FakeActivityPort:
    """Records calls; returns canned sequences."""

    def __init__(self):
        self.list_for_workspace_calls = []
        self.list_sessions_calls = []

    def list_for_workspace(self, query):
        self.list_for_workspace_calls.append(query)
        return ["event"]

    def list_active_workspace_sessions(self, *, workspace_id, limit):
        self.list_sessions_calls.append((workspace_id, limit))
        return ["session"]


def _policy(enabled):
    return OrgAuditVisibilityPolicy(settings_port=FakeOrgAuditLogSettings(enabled=enabled))


class TestOrgAuditVisibilityPolicy:
    def test_enabled_passes_silently(self):
        _policy(True).ensure_visible(uuid4())  # no raise

    def test_disabled_raises_with_machine_code(self):
        with pytest.raises(OrgAuditLogDisabledError) as excinfo:
            _policy(False).ensure_visible(uuid4())
        assert excinfo.value.code == "org_audit_log_disabled"


class TestGetOrgAuditLogSettingsUseCase:
    def test_returns_port_value(self):
        assert (
            GetOrgAuditLogSettingsUseCase(settings_port=FakeOrgAuditLogSettings(True)).execute(workspace_id=uuid4())
            is True
        )
        assert (
            GetOrgAuditLogSettingsUseCase(settings_port=FakeOrgAuditLogSettings(False)).execute(workspace_id=uuid4())
            is False
        )


class TestSetOrgAuditLogSettingsUseCase:
    def test_flips_and_returns_stored_value(self):
        port = FakeOrgAuditLogSettings(True)
        use_case = SetOrgAuditLogSettingsUseCase(settings_port=port)
        workspace_id, admin_id = uuid4(), uuid4()

        assert use_case.execute(workspace_id=workspace_id, enabled=False, changed_by=admin_id) is False
        assert use_case.execute(workspace_id=workspace_id, enabled=True, changed_by=admin_id) is True
        assert port.set_calls == [(workspace_id, False), (workspace_id, True)]

    def test_coerces_truthy_input_to_bool(self):
        port = FakeOrgAuditLogSettings(False)
        use_case = SetOrgAuditLogSettingsUseCase(settings_port=port)

        assert use_case.execute(workspace_id=uuid4(), enabled=1, changed_by=uuid4()) is True


class TestOrgListUseCasesConsultPolicy:
    def test_list_login_activity_blocked_when_disabled(self):
        activity = FakeActivityPort()
        use_case = ListWorkspaceLoginActivityUseCase(activity_port=activity, visibility_policy=_policy(False))
        query = WorkspaceLoginActivityQuery(workspace_id=uuid4())

        with pytest.raises(OrgAuditLogDisabledError):
            use_case.execute(query)
        assert activity.list_for_workspace_calls == []

    def test_list_login_activity_passes_when_enabled(self):
        activity = FakeActivityPort()
        use_case = ListWorkspaceLoginActivityUseCase(activity_port=activity, visibility_policy=_policy(True))
        query = WorkspaceLoginActivityQuery(workspace_id=uuid4())

        assert use_case.execute(query) == ["event"]
        assert activity.list_for_workspace_calls == [query]

    def test_list_sessions_blocked_when_disabled(self):
        activity = FakeActivityPort()
        use_case = ListWorkspaceSessionsUseCase(activity_port=activity, visibility_policy=_policy(False))

        with pytest.raises(OrgAuditLogDisabledError):
            use_case.execute(workspace_id=uuid4())
        assert activity.list_sessions_calls == []

    def test_list_sessions_passes_when_enabled(self):
        activity = FakeActivityPort()
        use_case = ListWorkspaceSessionsUseCase(activity_port=activity, visibility_policy=_policy(True))

        assert use_case.execute(workspace_id=uuid4()) == ["session"]
        assert len(activity.list_sessions_calls) == 1
