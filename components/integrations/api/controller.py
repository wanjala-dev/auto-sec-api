"""AWS Organization onboarding endpoints (Settings ▸ Integrations).

Flow (the pattern production security vendors use):
1. ``POST /integrations/aws/`` — creates the connection and GENERATES the
   ``external_id`` (vendor-side, never customer-chosen — confused-deputy
   defense per AWS SEC03-BP09).
2. ``GET  /integrations/aws/<id>/cloudformation/`` — returns the generated
   CloudFormation template the customer launches in their MANAGEMENT account.
   With ``org_wide`` it includes a StackSet using **service-managed
   permissions + auto-deployment**, so every current and future member
   account gets the audit role automatically (no per-account tickets, drift
   detection catches tampering).
3. ``POST /integrations/aws/<id>/verify/`` — assume-role dry-run through the
   management role; on success discovers member accounts
   (``organizations:ListAccounts``) into AwsAccountLink rows. Verification is
   per-account so one broken account degrades — never breaks — the org.

Controllers here are THIN: parse a request DTO, call the application
service / use case resolved from the provider, serialize a resource DTO.
All ORM access lives in ``AwsConnectionRepository``; the STS/boto3 call
lives behind ``OrgVerificationPort``.
"""

from __future__ import annotations

import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.integrations.api.requests.create_aws_connection_request import (
    CreateAwsConnectionRequest,
)
from components.integrations.api.requests.log_source_request import (
    CreateLogSourceRequest,
    UpdateLogSourceRequest,
)
from components.integrations.api.requests.open_draft_pr_request import (
    OpenDraftPrRequest,
)
from components.integrations.api.requests.triage_capability_request import (
    SetTriageCapabilityRequest,
)
from components.integrations.api.requests.vcs_connection_request import (
    CreateVcsConnectionRequest,
    UpdateVcsConnectionRequest,
)
from components.integrations.api.resources.aws_connection_resource import (
    AwsConnectionResource,
)
from components.integrations.api.resources.draft_pr_resource import DraftPrResource
from components.integrations.api.resources.log_source_resource import LogSourceResource
from components.integrations.api.resources.triage_capability_resource import (
    TriageCapabilityResource,
)
from components.integrations.api.resources.vcs_connection_resource import VcsConnectionResource
from components.integrations.application.aws_connection_service import (
    OrgVerificationError,
)
from components.integrations.application.providers.aws_connection_provider import (
    get_aws_connection_service,
    get_onboarding_template_use_case,
)
from components.integrations.application.providers.log_source_provider import (
    get_log_source_service,
)
from components.integrations.application.providers.vcs_provider import (
    get_vcs_connection_service,
)
from components.membership.api.permissions import IsWorkspaceOwner, has_workspace_permission

logger = logging.getLogger(__name__)

CanManageIntegrations = has_workspace_permission("manage_integrations")


class AwsConnectionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws"

    def get(self, request, workspace_id):
        conns = get_aws_connection_service().list_connections(workspace_id)
        return Response({"success": True, "data": [AwsConnectionResource.from_model(c).to_dict() for c in conns]})

    def post(self, request, workspace_id):
        req = CreateAwsConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        conn, created = get_aws_connection_service().create_connection(
            workspace_id=workspace_id,
            created_by=request.user,
            name=req.name,
            role_name=req.role_name,
            management_account_id=req.management_account_id,
            org_wide=req.org_wide,
            regions=req.regions,
            trail_s3_bucket=req.trail_s3_bucket,
            sqs_queue_url=req.sqs_queue_url,
        )
        return Response(
            {"success": True, "data": AwsConnectionResource.from_model(conn).to_dict(), "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AwsConnectionTemplateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws-cloudformation"

    def get(self, request, workspace_id, connection_id):
        conn = get_aws_connection_service().get_connection(workspace_id, connection_id)
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)
        use_case = get_onboarding_template_use_case()
        fmt = (request.query_params.get("fmt") or "cloudformation").lower()
        if fmt == "terraform":
            return Response({"success": True, "format": "terraform", "data": use_case.terraform(conn)})
        region = (list(conn.regions or []) or ["us-east-1"])[0]
        return Response(
            {
                "success": True,
                "format": "cloudformation",
                "data": use_case.cloudformation(conn),
                # One-click quick-create URL (None when no hosted template is configured →
                # the wizard falls back to copy-the-template). org-wide keeps copy-template.
                "launch_url": None if conn.org_wide else use_case.launch_url(conn, region=region),
            }
        )


class AwsConnectionVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws-verify"

    def post(self, request, workspace_id, connection_id):
        service = get_aws_connection_service()
        conn = service.get_connection(workspace_id, connection_id)
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)
        try:
            conn = service.verify_connection(conn)
        except OrgVerificationError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"success": True, "data": AwsConnectionResource.from_model(conn).to_dict()})


class AwsConnectionScanView(APIView):
    """POST → enqueue an async CSPM (Prowler) scan for the connection's accounts.

    A scan is long-running, so this fans the work out onto the cloud-posture
    Celery queue and returns 202 immediately — Prowler never runs in the request
    path. It reuses the exact task the nightly scheduler dispatches; this is just
    the on-demand "Scan now" trigger.
    """

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws-scan"

    def post(self, request, workspace_id, connection_id):
        conn = get_aws_connection_service().get_connection(workspace_id, connection_id)
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)

        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        if not get_feature_flags_provider().is_feature_enabled("feature.cloud_posture", workspace_id=str(workspace_id)):
            return Response(
                {"success": False, "error": "cloud_posture_not_enabled"},
                status=status.HTTP_409_CONFLICT,
            )

        from components.cloud_posture.application.providers.scan_provider import (
            enqueue_connection_scan,
        )

        enqueued = enqueue_connection_scan(workspace_id=str(workspace_id), connection_id=str(connection_id))
        return Response(
            {"success": True, "data": {"status": "scanning", "enqueued": enqueued or 0}},
            status=status.HTTP_202_ACCEPTED,
        )


class FindingOpenDraftPrView(APIView):
    """POST /integrations/workspaces/<ws>/findings/<task_id>/open-draft-pr/

    The rung-1 HITL path for the triage agent's draft-PR capability: a human
    operator approves, and the use case (the single choke point for EVERY
    precondition — installed connection, repo allowlist, finding triaged and
    not needs_human, agent capability enabled) opens the draft PR. Thin:
    parse → use case → serialize. Idempotent — a finding that already has a
    draft PR returns the existing URL with 200.
    """

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-finding-open-draft-pr"

    _REASON_STATUS = {
        "finding_not_found": status.HTTP_404_NOT_FOUND,
        "no_github_connection": status.HTTP_409_CONFLICT,
        "connection_not_connected": status.HTTP_409_CONFLICT,
        "no_github_token": status.HTTP_409_CONFLICT,
        "repo_not_allowlisted": status.HTTP_409_CONFLICT,
        "finding_not_triaged": status.HTTP_409_CONFLICT,
        "finding_needs_human": status.HTTP_409_CONFLICT,
        "capability_disabled": status.HTTP_403_FORBIDDEN,
        "no_candidate_path": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "no_grounded_patch": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "candidate_file_not_in_repo": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "ambiguous_candidate_path": status.HTTP_422_UNPROCESSABLE_ENTITY,
        # Verification-above-the-model rejections — a destructive/broken patch
        # never opens a PR (fail closed). 4xx, not 502: the operator can act.
        "patch_empty_or_noop": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "patch_does_not_parse": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "patch_removes_definitions": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "patch_too_destructive": status.HTTP_422_UNPROCESSABLE_ENTITY,
    }

    def post(self, request, workspace_id, task_id):
        from components.integrations.application.ports.vcs_port import VcsApiError
        from components.integrations.application.providers.vcs_provider import (
            get_open_draft_pr_use_case,
        )
        from components.integrations.application.use_cases.open_draft_pr_use_case import (
            DraftPrPreconditionError,
        )

        req = OpenDraftPrRequest.from_payload(request.data)
        try:
            result = get_open_draft_pr_use_case().execute(
                workspace_id=str(workspace_id),
                task_id=str(task_id),
                performed_by=str(request.user.id),
                repo=req.repo,
            )
        except DraftPrPreconditionError as exc:
            return Response(
                {"success": False, "reason": exc.reason, "error": str(exc)},
                status=self._REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            )
        except VcsApiError as exc:
            logger.exception("open_draft_pr_endpoint vcs error workspace_id=%s task_id=%s", workspace_id, task_id)
            return Response(
                {"success": False, "reason": "vcs_api_error", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"success": True, "data": DraftPrResource.from_result(result).to_dict()},
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class AwsConnectionLogStreamView(APIView):
    """GET /integrations/workspaces/<ws>/aws/<id>/logstream/

    Recent parsed records from the connection's shipped logs — feeds the HUD
    LOG STREAM card. The role-assumed S3 read is EXPENSIVE relative to a UI
    poll, so the scan result is cached for 60s per connection; the card polls
    every ~30s and mostly hits cache. Read-only; never advances the ingest
    checkpoint (the detect loop owns that cursor).
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "integrations-aws-logstream"

    def get(self, request, workspace_id, connection_id):
        from django.core.cache import cache

        conn = get_aws_connection_service().get_connection(workspace_id, connection_id)
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)

        cache_key = f"logstream:{connection_id}"
        payload = cache.get(cache_key)
        if payload is None:
            from components.integrations.application.log_ingest_service import scan_connection

            try:
                result = scan_connection(conn, max_objects=4, only_new=False)
            except Exception as exc:
                # A polling HUD card must never 502-spam. A connection with no
                # shipped-log source (no CloudTrail bucket → empty bucket name)
                # or a transient read failure degrades to an EMPTY stream the
                # card renders quietly — not an error toast every ~30s. Real
                # ingestion errors are owned/surfaced by the detect loop.
                logger.warning("logstream_unavailable connection_id=%s reason=%s", connection_id, str(exc)[:200])
                payload = {
                    "records": [],
                    "by_service": {},
                    "records_parsed": 0,
                    "errors": 0,
                    "error_records": [],
                    "newest_key": "",
                    "status": "unavailable",
                }
                cache.set(cache_key, payload, 60)
                return Response({"success": True, "data": payload})
            payload = {
                "records": [
                    {"service": r.service, "level": r.level, "message": r.message[:220]} for r in result.tail[-80:]
                ],
                "by_service": result.by_service,
                "records_parsed": result.records_parsed,
                "errors": len(result.errors),
                # The flagged lines themselves — drives the Anomalies hex
                # glitch + its click-through error list on the HUD.
                "error_records": [
                    {"service": e.service, "level": e.level, "message": e.message[:300]} for e in result.errors[-20:]
                ],
                "newest_key": result.newest_key,
                "status": "ok",
            }
            cache.set(cache_key, payload, 60)
        return Response({"success": True, "data": payload})


# ── WorkspaceLogSource CRUD (ADR 0008 Phase 3) — configure one or many log
#    sources per workspace (S3 today; CloudWatch/Datadog/Splunk as adapters land).


class WorkspaceLogSourceListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-log-sources"

    def get(self, request, workspace_id):
        sources = get_log_source_service().list_sources(workspace_id)
        return Response({"success": True, "data": [LogSourceResource.from_model(s).to_dict() for s in sources]})

    def post(self, request, workspace_id):
        req = CreateLogSourceRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        source = get_log_source_service().create_source(
            workspace_id=workspace_id, kind=req.kind, name=req.name, config=req.config
        )
        return Response(
            {"success": True, "data": LogSourceResource.from_model(source).to_dict()},
            status=status.HTTP_201_CREATED,
        )


class WorkspaceLogSourceDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-log-source-detail"

    def patch(self, request, workspace_id, source_id):
        service = get_log_source_service()
        source = service.get_source(workspace_id, source_id)
        if source is None:
            return Response({"success": False, "error": "Log source not found."}, status=404)
        req = UpdateLogSourceRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        source = service.update_source(source, name=req.name, config=req.config, status=req.status)
        return Response({"success": True, "data": LogSourceResource.from_model(source).to_dict()})

    def delete(self, request, workspace_id, source_id):
        service = get_log_source_service()
        source = service.get_source(workspace_id, source_id)
        if source is None:
            return Response({"success": False, "error": "Log source not found."}, status=404)
        service.delete_source(source)
        return Response({"success": True, "deleted": True})


class WorkspaceLogSourceVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-log-source-verify"

    def post(self, request, workspace_id, source_id):
        service = get_log_source_service()
        source = service.get_source(workspace_id, source_id)
        if source is None:
            return Response({"success": False, "error": "Log source not found."}, status=404)
        source = service.verify_source(source)
        return Response({"success": True, "data": LogSourceResource.from_model(source).to_dict()})


# ── VcsConnection CRUD (ADR 0010 Phase 3) — link one or many code-host connections
#    (GitHub today; GitLab/Bitbucket as adapters land) for agent draft-PR remediation.


class VcsConnectionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vcs-connections"

    def get(self, request, workspace_id):
        connections = get_vcs_connection_service().list_connections(workspace_id)
        return Response({"success": True, "data": [VcsConnectionResource.from_model(c).to_dict() for c in connections]})

    def post(self, request, workspace_id):
        req = CreateVcsConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        connection = get_vcs_connection_service().create_connection(
            workspace_id=workspace_id,
            provider=req.provider,
            name=req.name,
            repo_allowlist=req.repo_allowlist,
            base_url=req.base_url,
            repo_root=req.repo_root,
            commit_identity=req.commit_identity,
            commit_author_name=req.commit_author_name,
            commit_author_email=req.commit_author_email,
            token=req.token,
        )
        return Response(
            {"success": True, "data": VcsConnectionResource.from_model(connection).to_dict()},
            status=status.HTTP_201_CREATED,
        )


class VcsConnectionDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vcs-connection-detail"

    def patch(self, request, workspace_id, connection_id):
        service = get_vcs_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "VCS connection not found."}, status=404)
        req = UpdateVcsConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        connection = service.update_connection(
            connection,
            name=req.name,
            repo_allowlist=req.repo_allowlist,
            base_url=req.base_url,
            repo_root=req.repo_root,
            commit_identity=req.commit_identity,
            commit_author_name=req.commit_author_name,
            commit_author_email=req.commit_author_email,
            status=req.status,
            token=req.token,
        )
        return Response({"success": True, "data": VcsConnectionResource.from_model(connection).to_dict()})

    def delete(self, request, workspace_id, connection_id):
        service = get_vcs_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "VCS connection not found."}, status=404)
        service.delete_connection(connection)
        return Response({"success": True, "deleted": True})


class VcsConnectionVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vcs-connection-verify"

    def post(self, request, workspace_id, connection_id):
        service = get_vcs_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "VCS connection not found."}, status=404)
        connection = service.verify_connection(connection)
        return Response({"success": True, "data": VcsConnectionResource.from_model(connection).to_dict()})


# ── Triage-agent capability toggle (ADR 0010) — the last mile of the draft-PR
#    loop: give an OWNER a way to turn ``open_draft_pr`` ON/OFF for this
#    workspace's triage agent. Co-located with the VcsConnection consent
#    boundary and OWNER-gated (stricter than manage_integrations) because
#    granting an agent the power to open PRs is a high-privilege consent action.
#    The mutation lives in the AGENTS context (it owns Agent.config); this thin
#    controller calls that context's application service — never the Agent ORM.


class TriageCapabilityView(APIView):
    """GET/PATCH /integrations/workspaces/<ws>/triage-capabilities/

    GET returns the current capability map (every allowlisted key → bool) so the
    FE toggle can render its state without a write. PATCH flips one capability
    (``open_draft_pr`` by default), ensuring the ``triage_agent`` row on a fresh
    workspace so the toggle works day one. Idempotent — re-sending the same
    value returns the same state and writes no duplicate audit row.
    """

    permission_classes = (permissions.IsAuthenticated, IsWorkspaceOwner)
    name = "integrations-triage-capabilities"

    def get(self, request, workspace_id):
        from components.agents.application.service import AgentsService

        result = AgentsService().workspace_agent_capabilities(workspace_id=str(workspace_id))
        return Response({"success": True, "data": TriageCapabilityResource.from_result(result).to_dict()})

    def patch(self, request, workspace_id):
        from components.agents.application.service import AgentsService
        from components.shared_kernel.domain.errors import NotFoundError, ValidationError

        req = SetTriageCapabilityRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = AgentsService().set_workspace_agent_capability(
                workspace_id=str(workspace_id),
                capability=req.capability,
                enabled=req.enabled,
                actor=request.user,
            )
        except ValidationError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except NotFoundError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": TriageCapabilityResource.from_result(result).to_dict()})
