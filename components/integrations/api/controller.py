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

from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.integrations.api.requests.create_aws_connection_request import (
    CreateAwsConnectionRequest,
)
from components.integrations.api.requests.delivery_connection_request import (
    CreateDeliveryConnectionRequest,
    UpdateDeliveryConnectionRequest,
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
from components.integrations.api.requests.vercel_connection_request import (
    CreateVercelConnectionRequest,
    UpdateVercelConnectionRequest,
)
from components.integrations.api.resources.aws_connection_resource import (
    AwsConnectionResource,
)
from components.integrations.api.resources.delivery_connection_resource import (
    DeliveryConnectionResource,
)
from components.integrations.api.resources.draft_pr_preview_resource import DraftPrPreviewResource
from components.integrations.api.resources.draft_pr_resource import DraftPrResource
from components.integrations.api.resources.log_source_resource import LogSourceResource
from components.integrations.api.resources.triage_capability_resource import (
    TriageCapabilityResource,
)
from components.integrations.api.resources.vcs_connection_resource import VcsConnectionResource
from components.integrations.api.resources.vercel_connection_resource import (
    VercelConnectionResource,
)
from components.integrations.application.aws_connection_service import (
    OrgVerificationError,
)
from components.integrations.application.providers.aws_connection_provider import (
    get_aws_connection_service,
    get_onboarding_template_use_case,
)
from components.integrations.application.providers.delivery_channel_provider import (
    get_delivery_connection_service,
)
from components.integrations.application.providers.log_source_provider import (
    get_log_source_service,
)
from components.integrations.application.providers.vcs_provider import (
    get_vcs_connection_service,
)
from components.integrations.application.providers.vercel_provider import (
    get_vercel_connection_service,
)
from components.membership.api.permissions import IsWorkspaceOwner, has_workspace_permission

logger = logging.getLogger(__name__)

CanManageIntegrations = has_workspace_permission("manage_integrations")
# The on-demand draft-fix action mutates the finding's triage state as well as
# reaching the repo, so it demands the finding capability too (see the view).
CanManageFindings = has_workspace_permission("manage_findings")


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

        # Provenance: the operator pressing "Scan now" is stamped onto every
        # ScanRun the fan-out creates (this used to be dropped on the floor).
        result = enqueue_connection_scan(
            workspace_id=str(workspace_id),
            connection_id=str(connection_id),
            triggered_by=request.user.id,
        )
        if result is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)
        if result["enqueued"] == 0 and result["blocked"] > 0:
            # Every account is gated (in-flight or cooling down) — honest 429,
            # mirroring the code_security scan endpoint's budget rejection.
            body = {
                "success": False,
                "error": "scan_gated",
                "blocked": result["blocked"],
            }
            if result["retry_after"] is not None:
                body["retry_after"] = result["retry_after"]
            response = Response(body, status=429)
            if result["retry_after"] is not None:
                response["Retry-After"] = str(result["retry_after"])
            return response
        return Response(
            {
                "success": True,
                "data": {
                    "status": "scanning",
                    "enqueued": result["enqueued"],
                    "blocked": result["blocked"],
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )


class FindingOpenDraftPrView(APIView):
    """POST /integrations/workspaces/<ws>/findings/<task_id>/open-draft-pr/

    The rung-1 HITL path for the triage agent's draft-PR capability: a human
    operator approves, and the use case (the single choke point for EVERY
    precondition — installed connection, repo allowlist, finding triaged, agent
    capability enabled) opens the draft PR. An ungrounded/low-confidence fix is
    NOT a refusal any more: it opens labeled [UNVERIFIED] (verification is a
    label, not a gate). Thin: parse → use case → serialize. Idempotent — a
    finding that already has a draft PR returns the existing URL with 200.
    """

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-finding-open-draft-pr"

    _REASON_STATUS = {
        "finding_not_found": status.HTTP_404_NOT_FOUND,
        "no_github_connection": status.HTTP_409_CONFLICT,
        "connection_not_connected": status.HTTP_409_CONFLICT,
        "no_github_token": status.HTTP_409_CONFLICT,
        "repo_not_allowlisted": status.HTTP_409_CONFLICT,
        # The finding's own repo wins target resolution; these are the hard
        # guards that replaced the allowlist-head fallback (cross-repo
        # misdirection): the finding's repo missing from the allowlist, or an
        # explicit request targeting a different repo than the finding's own.
        "finding_repo_not_allowlisted": status.HTTP_409_CONFLICT,
        "finding_repo_mismatch": status.HTTP_409_CONFLICT,
        "finding_not_triaged": status.HTTP_409_CONFLICT,
        # SAST gate (ADR 0019 D5): the per-repo open-PR throttle is retriable
        # once open PRs merge/close. (The old ``finding_needs_human`` /
        # ``low_confidence`` refusals became the [UNVERIFIED] label — the PR
        # opens, marked, instead of being withheld.)
        "sast_pr_throttled": status.HTTP_429_TOO_MANY_REQUESTS,
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
        # Untrusted-repo-content guard: a SAST patch that reaches outside the
        # flagged file / finding window is refused mechanically.
        "patch_out_of_scope": status.HTTP_422_UNPROCESSABLE_ENTITY,
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


class FindingPreviewDraftPrView(APIView):
    """POST /integrations/workspaces/<ws>/findings/<task_id>/preview-draft-pr/

    Preview-before-commit (ADR 0012 P6): returns the grounded proposed patch (as a
    unified diff) + the vetted priors that grounded it, WITHOUT opening a PR. It runs
    the SAME preconditions and the SAME ``validate_patch`` guardrail as the open path
    (a destructive/broken patch yields the same ``patch_*`` 422 here — a preview can
    never present an unsafe patch as ready), and it posts the preview to the finding's
    board card as provenance. Opening a PR still goes through the separate open
    endpoint + its sign-off/approval — preview grounds, it never authorises (D2)."""

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-finding-preview-draft-pr"

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
            result = get_open_draft_pr_use_case().preview(
                workspace_id=str(workspace_id),
                task_id=str(task_id),
                performed_by=str(request.user.id),
                repo=req.repo,
            )
        except DraftPrPreconditionError as exc:
            return Response(
                {"success": False, "reason": exc.reason, "error": str(exc)},
                status=FindingOpenDraftPrView._REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            )
        except VcsApiError as exc:
            logger.exception("preview_draft_pr_endpoint vcs error workspace_id=%s task_id=%s", workspace_id, task_id)
            return Response(
                {"success": False, "reason": "vcs_api_error", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"success": True, "data": DraftPrPreviewResource.from_result(result).to_dict()})


class FindingDraftFixView(APIView):
    """POST /integrations/workspaces/<ws>/findings/<task_id>/draft-fix/

    The operator's on-demand "draft a fix PR" action — the THIRD trigger onto the
    one triage engine (the other two are automatic-on-detection and the cadence).

    Non-blocking by contract: this enqueues a Celery task and returns **202** with
    the finding's new state (``drafting``). The deep pipeline behind it is 10–30s of
    LLM calls; running it in-request would block daphne, which is a standing problem
    (#88) this must not extend. The HUD reconciles the real state by re-reading the
    finding, so the click is never a dead click.

    Authorisation is deliberately the SAME as the sibling ``open-draft-pr`` endpoint
    this action culminates in (``manage_integrations``) plus ``manage_findings`` for
    the finding mutation it performs. Gating on ``manage_findings`` alone would open
    a second, more permissive door onto a write into the customer's repository —
    a privilege escalation, not a convenience. Read-only viewers get 403.

    Safety invariant: a fix that fails a HARD guardrail — out-of-patch-scope,
    destructive/broken patch, over the per-repo SAST throttle, no connection /
    allowlist / capability — opens NO pull request; the reason is recorded on
    the card and surfaced in the finding's triage state. An ungrounded or
    low-confidence fix is NOT a hard failure: its draft PR opens labeled
    [UNVERIFIED] with the named evidence gap (verification is a label, not a
    gate — the draft PR is the human review surface).
    """

    permission_classes = (permissions.IsAuthenticated, CanManageFindings, CanManageIntegrations)
    name = "integrations-finding-draft-fix"

    _REASON_STATUS = {
        "finding_not_found": status.HTTP_404_NOT_FOUND,
        "not_routable": status.HTTP_409_CONFLICT,
        # The artifact must match the remediation target: a finding with no
        # linked repository (public/unlinked container image, cloud resource)
        # has nothing to open a PR against — its fix ships as a snippet on the
        # finding. Typed refusal, before any specialist run is burned.
        "no_repo_target": status.HTTP_409_CONFLICT,
        "draft_pr_exists": status.HTTP_409_CONFLICT,
        "ai_unavailable": status.HTTP_409_CONFLICT,
    }

    def post(self, request, workspace_id, task_id):
        from components.agents.application.ports.finding_dispatch_port import DraftFixRefused
        from components.agents.application.providers.ai_provider import AIProvider

        try:
            data = AIProvider.build_finding_dispatch_port().request_draft_fix(
                workspace_id=str(workspace_id), task_id=str(task_id), performed_by=str(request.user.id)
            )
        except DraftFixRefused as exc:
            return Response(
                {"success": False, "reason": exc.reason, "error": str(exc)},
                status=self._REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            )
        return Response({"success": True, "data": data}, status=status.HTTP_202_ACCEPTED)


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


# ── VercelConnection CRUD + verify + scan (ADR 0021 D2/D3) — link the ONE Vercel
#    team a workspace consents to posture-scan. Token-shaped (the GitHub-PAT
#    precedent); the pillar is dark behind feature.vercel_posture (D6): create and
#    scan are flag-gated 403 (no connect surface, no scan Jobs while dark); reads
#    and lifecycle on EXISTING rows stay available so an operator can still
#    disable/remove a connection after the flag is turned off.


def _vercel_posture_enabled(workspace_id) -> bool:
    """Fail-closed check of the pillar's dark-launch flag (ADR 0021 D6)."""
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )

    try:
        return bool(
            get_feature_flags_provider().is_feature_enabled("feature.vercel_posture", workspace_id=str(workspace_id))
        )
    except Exception:
        logger.exception("vercel_posture flag check failed workspace=%s", workspace_id)
        return False


_VERCEL_POSTURE_DISABLED_RESPONSE = {
    "success": False,
    "error": "vercel_posture_not_enabled",
}


@method_decorator(sensitive_post_parameters("token"), name="dispatch")
class VercelConnectionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vercel-connections"

    def get(self, request, workspace_id):
        connections = get_vercel_connection_service().list_connections(workspace_id)
        return Response(
            {"success": True, "data": [VercelConnectionResource.from_model(c).to_dict() for c in connections]}
        )

    def post(self, request, workspace_id):
        if not _vercel_posture_enabled(workspace_id):
            return Response(_VERCEL_POSTURE_DISABLED_RESPONSE, status=status.HTTP_403_FORBIDDEN)
        req = CreateVercelConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        team_id, team_slug = req.team_parts
        connection = get_vercel_connection_service().create_connection(
            workspace_id=workspace_id,
            name=req.name,
            team_id=team_id,
            team_slug=team_slug,
            token=req.token,
            created_by=request.user,
        )
        return Response(
            {"success": True, "data": VercelConnectionResource.from_model(connection).to_dict()},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(sensitive_post_parameters("token"), name="dispatch")
class VercelConnectionDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vercel-connection-detail"

    def patch(self, request, workspace_id, connection_id):
        service = get_vercel_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Vercel connection not found."}, status=404)
        req = UpdateVercelConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        team_parts = req.team_parts
        connection = service.update_connection(
            connection,
            name=req.name,
            team_id=team_parts[0] if team_parts is not None else None,
            team_slug=team_parts[1] if team_parts is not None else None,
            status=req.status,
            token=req.token,
        )
        return Response({"success": True, "data": VercelConnectionResource.from_model(connection).to_dict()})

    def delete(self, request, workspace_id, connection_id):
        service = get_vercel_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Vercel connection not found."}, status=404)
        service.delete_connection(connection)
        return Response({"success": True, "deleted": True})


class VercelConnectionVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vercel-connection-verify"

    def post(self, request, workspace_id, connection_id):
        service = get_vercel_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Vercel connection not found."}, status=404)
        connection = service.verify_connection(connection)
        return Response({"success": True, "data": VercelConnectionResource.from_model(connection).to_dict()})


class VercelConnectionScanView(APIView):
    """POST → gate + enqueue one async Prowler ``vercel`` posture scan (ADR 0021 D3).

    Rides the scanning spine: the trigger use case takes the anti-spam dispatch
    lock (one in-flight scan per team, one completed scan per cooldown window) and
    dispatches the generic ``scanning.run_scan`` task — Prowler never runs in the
    request path. 403 while the pillar is dark (D6); budget rejections are 429
    with Retry-After (the code_security mapping).
    """

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-vercel-connection-scan"

    def post(self, request, workspace_id, connection_id):
        if not _vercel_posture_enabled(workspace_id):
            return Response(_VERCEL_POSTURE_DISABLED_RESPONSE, status=status.HTTP_403_FORBIDDEN)
        connection = get_vercel_connection_service().get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Vercel connection not found."}, status=404)
        if connection.status == connection.Status.DISABLED:
            return Response(
                {"success": False, "error": "This Vercel connection is disabled."},
                status=status.HTTP_409_CONFLICT,
            )
        if not connection.team_ref:
            return Response(
                {"success": False, "error": "No team configured — verify the connection first."},
                status=status.HTTP_409_CONFLICT,
            )

        from components.cloud_posture.application.providers.scan_provider import trigger_vercel_scan
        from components.cloud_posture.application.use_cases.trigger_vercel_scan_use_case import (
            VercelScanRejected,
        )

        try:
            result = trigger_vercel_scan(
                workspace_id=workspace_id,
                connection_id=connection.id,
                team=connection.team_ref,
                trigger="manual",
                triggered_by=request.user.id,
            )
        except VercelScanRejected as exc:
            # Budget rejections are 429 (retriable, with Retry-After); shape
            # rejections are 400 — the code_security controller's mapping.
            body = {"success": False, "error": exc.code, "detail": str(exc)}
            if exc.code in ("scan_cooldown", "scan_already_running"):
                if exc.retry_after:
                    body["retry_after"] = exc.retry_after
                response = Response(body, status=429)
                if exc.retry_after:
                    response["Retry-After"] = str(exc.retry_after)
                return response
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"success": True, "data": {"status": "scanning", **result}},
            status=status.HTTP_202_ACCEPTED,
        )


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


# ── DeliveryConnection CRUD + verify (ADR 0016 D2) — Settings ▸ Integrations ▸
#    Notification Channels. Where a workspace connects Slack (and, as adapters land,
#    Teams / Discord / generic webhook / SMTP) so alerts reach the team where they work.
#
#    The credential is WRITE-ONLY throughout: it is accepted on create/update, stored in
#    the Fernet envelope, and never returned — reads carry only ``has_secret``. Verify
#    answers 200 on failure too, expressing the outcome as ``status="error"`` +
#    ``last_error``, because the operator needs to see why in the panel.


@method_decorator(sensitive_post_parameters("secret"), name="dispatch")
class DeliveryConnectionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-delivery-connections"

    def get(self, request, workspace_id):
        connections = get_delivery_connection_service().list_connections(workspace_id)
        return Response(
            {"success": True, "data": [DeliveryConnectionResource.from_model(c).to_dict() for c in connections]}
        )

    def post(self, request, workspace_id):
        req = CreateDeliveryConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        connection = get_delivery_connection_service().create_connection(
            workspace_id=workspace_id,
            kind=req.kind,
            name=req.name,
            auth_mode=req.auth_mode,
            secret=req.secret,
            channel=req.channel,
            min_severity=req.min_severity,
            events=req.events,
            created_by_id=getattr(request.user, "id", None),
        )
        return Response(
            {"success": True, "data": DeliveryConnectionResource.from_model(connection).to_dict()},
            status=status.HTTP_201_CREATED,
        )


@method_decorator(sensitive_post_parameters("secret"), name="dispatch")
class DeliveryConnectionDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-delivery-connection-detail"

    def patch(self, request, workspace_id, connection_id):
        service = get_delivery_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Delivery connection not found."}, status=404)
        req = UpdateDeliveryConnectionRequest.from_payload(request.data)
        error = req.validation_error()
        if error:
            return Response({"success": False, "error": error}, status=status.HTTP_400_BAD_REQUEST)
        connection = service.update_connection(
            connection,
            name=req.name,
            auth_mode=req.auth_mode,
            secret=req.secret,
            channel=req.channel,
            min_severity=req.min_severity,
            events=req.events,
            status=req.status,
            is_enabled=req.is_enabled,
        )
        return Response({"success": True, "data": DeliveryConnectionResource.from_model(connection).to_dict()})

    def delete(self, request, workspace_id, connection_id):
        service = get_delivery_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Delivery connection not found."}, status=404)
        service.delete_connection(connection)
        return Response({"success": True, "deleted": True})


class DeliveryConnectionVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-delivery-connection-verify"

    def post(self, request, workspace_id, connection_id):
        service = get_delivery_connection_service()
        connection = service.get_connection(workspace_id, connection_id)
        if connection is None:
            return Response({"success": False, "error": "Delivery connection not found."}, status=404)
        connection = service.verify_connection(connection)
        return Response({"success": True, "data": DeliveryConnectionResource.from_model(connection).to_dict()})
