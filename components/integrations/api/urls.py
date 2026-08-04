"""Integrations routes — AWS Organization onboarding + GitHub draft-PR. Mounted at /integrations/."""

from django.urls import path

from components.integrations.api.controller import (
    AwsConnectionListCreateView,
    AwsConnectionLogStreamView,
    AwsConnectionScanView,
    AwsConnectionTemplateView,
    AwsConnectionVerifyView,
    DeliveryConnectionDetailView,
    DeliveryConnectionListCreateView,
    DeliveryConnectionVerifyView,
    FindingOpenDraftPrView,
    FindingPreviewDraftPrView,
    TriageCapabilityView,
    VcsConnectionDetailView,
    VcsConnectionListCreateView,
    VcsConnectionVerifyView,
    WorkspaceLogSourceDetailView,
    WorkspaceLogSourceListCreateView,
    WorkspaceLogSourceVerifyView,
)

urlpatterns = [
    path(
        "workspaces/<uuid:workspace_id>/aws/",
        AwsConnectionListCreateView.as_view(),
        name=AwsConnectionListCreateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/cloudformation/",
        AwsConnectionTemplateView.as_view(),
        name=AwsConnectionTemplateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/verify/",
        AwsConnectionVerifyView.as_view(),
        name=AwsConnectionVerifyView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/scan/",
        AwsConnectionScanView.as_view(),
        name=AwsConnectionScanView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/aws/<uuid:connection_id>/logstream/",
        AwsConnectionLogStreamView.as_view(),
        name=AwsConnectionLogStreamView.name,
    ),
    path(
        # str, not int/uuid: Task pks are integers today, but the use case
        # validates the id itself and answers a typed finding_not_found —
        # a malformed id must yield that JSON error, not a bare URL 404.
        "workspaces/<uuid:workspace_id>/findings/<str:task_id>/open-draft-pr/",
        FindingOpenDraftPrView.as_view(),
        name=FindingOpenDraftPrView.name,
    ),
    path(
        # Preview-before-commit (ADR 0012 P6): show the grounded proposed patch +
        # its grounding provenance BEFORE opening a PR. Same guardrail, no commit.
        "workspaces/<uuid:workspace_id>/findings/<str:task_id>/preview-draft-pr/",
        FindingPreviewDraftPrView.as_view(),
        name=FindingPreviewDraftPrView.name,
    ),
    # ── Log sources (ADR 0008 Phase 3) ──
    path(
        "workspaces/<uuid:workspace_id>/log-sources/",
        WorkspaceLogSourceListCreateView.as_view(),
        name=WorkspaceLogSourceListCreateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/log-sources/<uuid:source_id>/",
        WorkspaceLogSourceDetailView.as_view(),
        name=WorkspaceLogSourceDetailView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/log-sources/<uuid:source_id>/verify/",
        WorkspaceLogSourceVerifyView.as_view(),
        name=WorkspaceLogSourceVerifyView.name,
    ),
    # ── VCS connections (ADR 0010 Phase 3) ──
    path(
        "workspaces/<uuid:workspace_id>/vcs-connections/",
        VcsConnectionListCreateView.as_view(),
        name=VcsConnectionListCreateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/vcs-connections/<uuid:connection_id>/",
        VcsConnectionDetailView.as_view(),
        name=VcsConnectionDetailView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/vcs-connections/<uuid:connection_id>/verify/",
        VcsConnectionVerifyView.as_view(),
        name=VcsConnectionVerifyView.name,
    ),
    # ── Triage-agent capability toggle (ADR 0010) — owner-gated ──
    path(
        "workspaces/<uuid:workspace_id>/triage-capabilities/",
        TriageCapabilityView.as_view(),
        name=TriageCapabilityView.name,
    ),
    # ── Delivery connections (ADR 0016 P1) — Settings ▸ Notification Channels ──
    path(
        "workspaces/<uuid:workspace_id>/delivery-connections/",
        DeliveryConnectionListCreateView.as_view(),
        name=DeliveryConnectionListCreateView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/delivery-connections/<uuid:connection_id>/",
        DeliveryConnectionDetailView.as_view(),
        name=DeliveryConnectionDetailView.name,
    ),
    path(
        "workspaces/<uuid:workspace_id>/delivery-connections/<uuid:connection_id>/verify/",
        DeliveryConnectionVerifyView.as_view(),
        name=DeliveryConnectionVerifyView.name,
    ),
]
