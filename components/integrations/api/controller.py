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
from components.integrations.api.requests.open_draft_pr_request import (
    OpenDraftPrRequest,
)
from components.integrations.api.resources.aws_connection_resource import (
    AwsConnectionResource,
)
from components.integrations.api.resources.draft_pr_resource import DraftPrResource
from components.integrations.application.aws_connection_service import (
    OrgVerificationError,
)
from components.integrations.application.providers.aws_connection_provider import (
    get_aws_connection_service,
    get_onboarding_template_use_case,
)
from components.membership.api.permissions import has_workspace_permission

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
        return Response(
            {
                "success": True,
                "format": "cloudformation",
                "data": use_case.cloudformation(conn),
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
    }

    def post(self, request, workspace_id, task_id):
        from components.integrations.application.ports.github_pr_port import GitHubApiError
        from components.integrations.application.providers.github_pr_provider import (
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
        except GitHubApiError as exc:
            logger.exception("open_draft_pr_endpoint github error workspace_id=%s task_id=%s", workspace_id, task_id)
            return Response(
                {"success": False, "reason": "github_api_error", "error": str(exc)},
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
                logger.exception("logstream_scan_failed connection_id=%s", connection_id)
                return Response(
                    {"success": False, "error": str(exc)[:300]},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
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
            }
            cache.set(cache_key, payload, 60)
        return Response({"success": True, "data": payload})
