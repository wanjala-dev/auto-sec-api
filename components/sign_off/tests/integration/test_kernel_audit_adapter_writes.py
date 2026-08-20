"""The sign-off decision trail must reach the database, not just a fake.

`sign_off` is the approval gate in front of high-risk actions. Its whole
product purpose is to leave a record of who approved what. Every existing test
of that trail asserts against `FakeSignOffAudit.entries` — an in-memory list —
which proves the SERVICE calls the port, and nothing whatsoever about whether
the production adapter writes a row. That gap is what let a guaranteed no-op
sit in the approval path unnoticed.

These tests drive the real `KernelSignOffAuditAdapter` against the real
`EntityAuditLog` repository and a real database, and assert on rows. A fake
appears nowhere in the audit path.
"""

from __future__ import annotations

import pytest

from components.sign_off.application.providers.sign_off_queue_provider import (
    SignOffQueueProvider,
)
from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)
from components.sign_off.tests.unit.fakes import FakeSignOffAdapter
from infrastructure.persistence.audit.models import EntityAuditLog

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

ARTIFACT_TYPE = "audited_fake"

# A real, migrated model, so ContentType resolution succeeds exactly as it does
# for the three production adapters (content.newsletter, content.writingdraft,
# workflows.workflowstepstate). `object_id` is a plain CharField with no FK
# integrity, so the id it carries need not exist — this is a log line, not a
# join.
AUDIT_CONTENT_TYPE = "content.newsletter"


class AuditableFakeAdapter(FakeSignOffAdapter):
    """The unit-test fake, plus the one thing the audit path actually needs."""

    def audit_content_type(self) -> str:
        return AUDIT_CONTENT_TYPE


@pytest.fixture
def registered_artifact(workspace_factory, user_factory):
    """A pending artifact of a registered type, owned by a real workspace.

    The artifact itself is a fake — the kernel never touches a foreign
    context's ORM, so what it stands for does not matter. The workspace and
    the audit sink are real, because those are what is under test.
    """
    workspace = workspace_factory(owner=user_factory())
    adapter = AuditableFakeAdapter(ARTIFACT_TYPE, workspace_id=str(workspace.id))
    registry = get_sign_off_registry()
    registry.register(adapter)
    return {"workspace": workspace, "adapter": adapter, "artifact_id": "artifact-1"}


def _service():
    """The production service, with the production audit adapter."""
    return SignOffQueueProvider().build_service()


def _rows(workspace) -> list[EntityAuditLog]:
    return list(EntityAuditLog.objects.filter(workspace=workspace, field_name="review_state"))


class TestApprovalIsAudited:
    def test_approve_writes_an_audit_row(self, registered_artifact):
        workspace = registered_artifact["workspace"]
        assert _rows(workspace) == []

        _service().approve(ARTIFACT_TYPE, registered_artifact["artifact_id"], actor_id=None)

        rows = _rows(workspace)
        assert len(rows) == 1, "an approval that leaves no trail is the failure sign_off exists to prevent"
        assert rows[0].new_value == "approved"
        assert str(rows[0].object_id) == registered_artifact["artifact_id"]

    def test_reject_writes_an_audit_row(self, registered_artifact):
        workspace = registered_artifact["workspace"]

        _service().reject(
            ARTIFACT_TYPE,
            registered_artifact["artifact_id"],
            actor_id=None,
            codes=("inaccurate",),
            note="numbers do not reconcile",
        )

        rows = _rows(workspace)
        assert len(rows) == 1
        assert rows[0].new_value == "rejected"
        assert rows[0].reason == "numbers do not reconcile"

    def test_the_row_is_scoped_to_the_artifacts_workspace(self, registered_artifact):
        """A trail written against the wrong tenant is worse than none."""
        workspace = registered_artifact["workspace"]

        _service().approve(ARTIFACT_TYPE, registered_artifact["artifact_id"], actor_id=None)

        rows = _rows(workspace)
        assert len(rows) == 1
        assert rows[0].workspace_id == workspace.id


class TestEveryProductionAdapterIsAuditable:
    """A fitness function over the registry, not over one adapter.

    ``audit_content_type()`` defaults to None on the port so that adding it was
    not a breaking change. That default is also a trap: a new adapter that
    forgets to override it is silently unauditable — the same class of defect
    this PR exists to fix, one context over. This fails the moment that
    happens.
    """

    def test_every_production_adapter_declares_a_resolvable_content_type(self):
        from django.contrib.contenttypes.models import ContentType

        from components.content.infrastructure.adapters.newsletter_sign_off_adapter import (
            NewsletterSignOffAdapter,
        )
        from components.content.infrastructure.adapters.writing_draft_sign_off_adapter import (
            WritingDraftSignOffAdapter,
        )
        from components.workflow.infrastructure.adapters.workflow_email_sign_off_adapter import (
            WorkflowEmailSignOffAdapter,
        )

        # Instantiated directly rather than read off the registry: the registry
        # is process-global and other tests register doubles into it, so a
        # registry walk would be order-dependent.
        adapters = [
            NewsletterSignOffAdapter(),
            WritingDraftSignOffAdapter(),
            WorkflowEmailSignOffAdapter(),
        ]

        unauditable, unresolvable = [], []
        for adapter in adapters:
            declared = adapter.audit_content_type()
            if not declared:
                unauditable.append(adapter.artifact_type())
                continue
            app_label, _, model_name = declared.partition(".")
            if not ContentType.objects.filter(app_label=app_label, model=model_name).exists():
                unresolvable.append((adapter.artifact_type(), declared))

        assert not unauditable, f"sign-off adapters with no audit content type: {unauditable}"
        assert not unresolvable, f"sign-off adapters naming a non-existent model: {unresolvable}"
