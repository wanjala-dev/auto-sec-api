"""Trigger-completeness contract tests.

A trigger is usable ONLY if (a) it is in ``TRIGGER_CATALOG`` (so the binding
serializer accepts it) AND (b) some context actually calls
``emit_workflow_event`` for it with a contact-bearing payload (so a run can
start). This suite locks both halves in sync for the triggers this PR touched:

WIRED (assert the binding can be created for catalogued triggers):
  * ``form_completed``  — in the catalog; emitter lived in the (removed) donation_forms context
  * ``email_sent``      — in the catalog; emitter lived in the (removed) content context
  * ``contact_updated`` — member-role change (membership groups_controller)

REMOVED (assert no longer in the catalog AND a binding to it is rejected):
  * ``contact_tagged``  — would loop through the add_tag executor; no manual
    tagging surface exists to emit it cleanly.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.workflow.domain.constants import SOURCE_TYPES, TRIGGER_CATALOG

pytestmark = pytest.mark.django_db


def _catalog_ids() -> set[str]:
    return {t.id for t in TRIGGER_CATALOG}


# ── Catalog membership (cheap, no DB) ──────────────────────────────────────
class TestCatalogMembership:
    def test_form_completed_in_catalog(self):
        trigger = next((t for t in TRIGGER_CATALOG if t.id == "form_completed"), None)
        assert trigger is not None
        assert trigger.source_type == "form"
        assert trigger.source_type in SOURCE_TYPES

    def test_email_sent_in_catalog(self):
        trigger = next((t for t in TRIGGER_CATALOG if t.id == "email_sent"), None)
        assert trigger is not None
        assert trigger.source_type == "communication"
        assert trigger.source_type in SOURCE_TYPES

    def test_contact_updated_in_catalog(self):
        trigger = next((t for t in TRIGGER_CATALOG if t.id == "contact_updated"), None)
        assert trigger is not None
        assert trigger.source_type == "directory"

    def test_contact_tagged_removed_from_catalog(self):
        assert "contact_tagged" not in _catalog_ids()


# ── Binding creation via the serializer (catalog contract) ─────────────────
class TestBindingCreatability:
    """A catalogued trigger must be acceptable to the binding serializer; a
    removed one must be rejected."""

    def _make_workflow(self, workspace):
        from infrastructure.persistence.workspaces.workflows.models import Workflow

        return Workflow.objects.create(
            workspace=workspace,
            name="Flow",
            goal="campaign",
            status=Workflow.Status.PUBLISHED,
            version=1,
            graph={"nodes": [{"id": "start", "type": "start"}], "edges": []},
        )

    def _serializer_is_valid(self, workflow, *, source_type, trigger_type):
        from components.workflow.mappers.rest.workflow_serializers import (
            WorkflowBindingSerializer,
        )

        serializer = WorkflowBindingSerializer(
            data={
                "workflow_id": str(workflow.id),
                "source_type": source_type,
                "trigger_type": trigger_type,
                "source_id": "",
                "is_active": True,
            }
        )
        return serializer.is_valid(), serializer.errors

    def test_form_completed_binding_accepted(self, workspace_factory):
        wf = self._make_workflow(workspace_factory())
        ok, errors = self._serializer_is_valid(wf, source_type="form", trigger_type="form_completed")
        assert ok, errors

    def test_email_sent_binding_accepted(self, workspace_factory):
        wf = self._make_workflow(workspace_factory())
        ok, errors = self._serializer_is_valid(wf, source_type="communication", trigger_type="email_sent")
        assert ok, errors

    def test_contact_updated_binding_accepted(self, workspace_factory):
        wf = self._make_workflow(workspace_factory())
        ok, errors = self._serializer_is_valid(wf, source_type="directory", trigger_type="contact_updated")
        assert ok, errors

    def test_contact_tagged_binding_rejected(self, workspace_factory):
        wf = self._make_workflow(workspace_factory())
        ok, errors = self._serializer_is_valid(wf, source_type="directory", trigger_type="contact_tagged")
        assert not ok
        assert "trigger_type" in errors


# ── contact_updated emit (membership member-role change) ────────────────────
@pytest.fixture(autouse=True)
def _need_system_roles(db):
    """Every test in this module resolves WorkspaceRole rows via
    _make_membership. The session-scoped default_system_roles seed is NOT
    enough: any transactional_db test running earlier in the same process
    flushes it (exposed by CI sharding, PR #682). Re-seed per test from the
    same migration source of truth — update_or_create keeps it cheap.
    """
    import importlib

    from django.apps import apps as django_apps

    migration = importlib.import_module("infrastructure.persistence.workspaces.migrations.0016_seed_system_roles")
    WorkspaceRole = django_apps.get_model("workspaces", "WorkspaceRole")
    for slug, name, description, permissions in migration.SYSTEM_ROLE_SEEDS:
        WorkspaceRole.objects.update_or_create(
            workspace=None,
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "permissions": list(permissions),
                "is_system": True,
            },
        )


def _make_membership(workspace, user, *, role_slug):
    from infrastructure.persistence.workspaces.models import (
        WorkspaceMembership,
        WorkspaceRole,
    )

    role_obj = WorkspaceRole.objects.get(workspace__isnull=True, slug=role_slug)
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role_slug if role_slug in dict(WorkspaceMembership.Role.choices) else "member",
        workspace_role=role_obj,
        status=WorkspaceMembership.Status.ACTIVE,
    )


class TestContactUpdatedEmit:
    """Changing a member's role emits contact_updated targeting the member."""

    def test_role_change_emits_contact_updated(self, workspace_factory, user_factory, api_client):
        from django.urls import reverse

        owner = user_factory()
        admin = user_factory()
        member = user_factory()
        workspace = workspace_factory(owner=owner)
        _make_membership(workspace, admin, role_slug="admin")
        _make_membership(workspace, member, role_slug="member")

        url = reverse(
            "workspace-member-role",
            kwargs={"workspace_id": str(workspace.id), "user_id": str(member.id)},
        )

        api_client.force_authenticate(user=admin)
        provider = mock.Mock()
        with mock.patch(
            "components.workflow.application.providers.workflow_dispatcher_provider.get_workflow_dispatcher_provider",
            return_value=provider,
        ):
            response = api_client.patch(url, {"role_slug": "finance"}, format="json")

        assert response.status_code == 200, response.data
        provider.emit_workflow_event.assert_called_once()
        kwargs = provider.emit_workflow_event.call_args.kwargs
        assert kwargs["trigger_type"] == "contact_updated"
        assert kwargs["source_type"] == "directory"
        payload = kwargs["payload"]
        assert payload["target_type"] == "contact"
        assert payload["target_id"] == str(member.id)
        assert payload["contact_id"] == str(member.id)
