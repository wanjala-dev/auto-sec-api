"""Consolidated controller module for all shared_platform HTTP endpoints.

This module consolidates view classes from:
- broadcast_controller: BannerViewSet
- core_controller: FeatureFlagsView, FeatureFlagStatusView
- honeypot_controller: HoneypotLoginView
- uploads_controller: File upload views
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.core.exceptions import RequestDataTooBig

from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)

_django_orm = _get_django_orm_provider()
Q = _django_orm.Q
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.generic import FormView
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions, status, viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_platform.api.permissions import (
    HasWorkspaceMembership,
    IsOwnerOrReadOnly,
)
from components.shared_platform.application.providers.feature_flags_provider import (
    get_feature_flags_provider,
)
from components.shared_platform.application.providers.honeypot_form_provider import (
    get_honeypot_form_provider,
)
from components.shared_platform.application.providers.upload_pagination_provider import (
    get_upload_pagination_provider,
)
from components.shared_platform.mappers.rest.broadcast_serializers import BannerSerializer
from components.shared_platform.mappers.rest.uploads_serializers import FileSerializer

# Module-level resolution of the form / pagination classes so existing
# class-attribute assignments (``form_class = HoneypotAuthenticationForm``
# and ``pagination_class = DefaultPagination``) keep working without
# touching every consuming view. The providers lazy-import on first
# call — fine at module load time because Django/DRF are already up.
HoneypotAuthenticationForm = get_honeypot_form_provider().get_form_class()
DefaultPagination = get_upload_pagination_provider().get_pagination_class()
from components.shared_platform.application.providers.broadcast_models_provider import get_broadcast_models_provider

Banner = get_broadcast_models_provider().Banner
from components.shared_platform.application.providers.core_models_provider import get_core_models_provider

FeatureFlag = get_core_models_provider().FeatureFlag
from components.shared_platform.application.providers.honeypot_models_provider import get_honeypot_models_provider

HoneypotAttempt = get_honeypot_models_provider().HoneypotAttempt
from components.shared_platform.application.providers.uploads_models_provider import get_uploads_models_provider

File = get_uploads_models_provider().File
from components.workspace.api.permissions import IsOrgOwnerOrMember
from components.workspace.api.workspace_permissions import (
    IsAdminUser,
)
from infrastructure.api.client_ip import trusted_client_ip

logger = logging.getLogger(__name__)

# =============================================================================
# BROADCAST (ANNOUNCEMENTS) VIEWS
# =============================================================================


class BannerViewSet(viewsets.ModelViewSet):
    """System / workspace / user banners.

    The write verbs were always gated correctly (``IsAdminUser`` for every
    action but ``list``/``retrieve``). The READ path was the defect: it was
    ``AllowAny``, and ``get_queryset()`` built its scope filter EXCLUSIVELY
    from client-supplied query parameters, never once consulting
    ``request.user``. An anonymous caller could therefore ask for
    ``?scope=user&user=<uuid>`` and receive that user's private banners —
    ``BannerSerializer`` exposes ``user_email`` — or ``?scope=workspace&
    workspace=<uuid>`` to cross a tenant boundary, or
    ``?scope=all&include_inactive=true`` to drop BOTH the scope filter and the
    active-window filter and read every banner of every scope, including
    unpublished ones.

    Scope is now DERIVED from the caller. The parameters survive as filters
    that can only narrow: an unknown or foreign value yields fewer rows, never
    an error, so existing clients keep working.
    """

    serializer_class = BannerSerializer
    queryset = Banner.objects.all()

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.IsAuthenticated()]
        return [IsAdminUser()]

    def get_queryset(self):
        user = self.request.user
        is_support = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
        queryset = Banner.objects.select_related("workspace", "user")

        if not getattr(user, "is_authenticated", False):
            return queryset.none()

        # Unpublished / expired banners are pre-announcement material.
        if not (is_support and self._param_true("include_inactive")):
            queryset = queryset.active()

        if is_support:
            queryset = self._apply_requested_narrowing(queryset)
            return queryset.order_by("priority", "-created_at")

        # A non-staff caller sees: system banners, their OWN user banners, and
        # banners for workspaces they can actually access. The client cannot
        # name a different user or an unaffiliated workspace.
        from components.shared_platform.application.providers.workspace_access_provider import (
            get_workspace_access_adapter,
        )

        accessible = get_workspace_access_adapter().accessible_workspace_ids(user_id=user.id)
        requested_workspace = (self.request.query_params.get("workspace") or "").strip()
        if requested_workspace:
            accessible = accessible & {requested_workspace}

        scope_filter = Q(scope=Banner.Scope.SYSTEM) | Q(scope=Banner.Scope.USER, user_id=user.id)
        if accessible:
            scope_filter |= Q(scope=Banner.Scope.WORKSPACE, workspace_id__in=accessible)

        scope_param = (self.request.query_params.get("scope") or "").strip().lower()
        if scope_param and scope_param != "all":
            scope_filter &= Q(scope=scope_param)

        return queryset.filter(scope_filter).order_by("priority", "-created_at")

    def _apply_requested_narrowing(self, queryset):
        """Staff-only: honour the raw scope parameters for support tooling."""
        scope_param = self.request.query_params.get("scope")
        scope_value = scope_param.lower() if scope_param else None
        workspace_id = self.request.query_params.get("workspace")
        user_id = self.request.query_params.get("user")

        if scope_value and scope_value != "all":
            queryset = queryset.filter(scope=scope_value)
            if scope_value == Banner.Scope.WORKSPACE and workspace_id:
                queryset = queryset.filter(workspace_id=workspace_id)
            if scope_value == Banner.Scope.USER and user_id:
                queryset = queryset.filter(user_id=user_id)
            return queryset

        scope_filter = Q(scope=Banner.Scope.SYSTEM)
        if workspace_id:
            scope_filter |= Q(scope=Banner.Scope.WORKSPACE, workspace_id=workspace_id)
        if user_id:
            scope_filter |= Q(scope=Banner.Scope.USER, user_id=user_id)
        return queryset.filter(scope_filter)

    def _param_true(self, name: str) -> bool:
        value = self.request.query_params.get(name, "")
        return str(value).lower() in {"1", "true", "yes"}


# =============================================================================
# CORE (FEATURE FLAGS) VIEWS
# =============================================================================


class FeatureFlagsView(APIView):
    """
    Return evaluated feature flags for the requesting user and workspace context.

    Query params:
    - workspace_id: UUID (optional; falls back to user's active workspace)
    - include_sources=1: include evaluation sources (staff only)

    A workspace's evaluated flags ARE its product configuration — which
    scanners and capabilities are on, whether it is running on sample data,
    whether the AI kill switch is tripped. ``HasWorkspaceMembership`` is
    therefore mandatory, not decorative: ``workspace_id`` arrives from the
    caller, and autosec is single-DB with application-enforced isolation, so
    an unchecked workspace param IS the cross-tenant boundary (ADR 0028).
    When no workspace is named the permission stands down and the resolver
    falls back to the caller's OWN active workspace — that path is safe, and
    gating it would 403 the first-run bootstrap that runs before a workspace
    is chosen.
    """

    permission_classes = [permissions.IsAuthenticated, HasWorkspaceMembership]

    def get(self, request, format=None):
        _flags = get_feature_flags_provider()
        workspace_id = request.query_params.get("workspace_id") or _flags.resolve_workspace_id_from_request(request)
        include_sources = bool(request.query_params.get("include_sources")) and bool(
            getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)
        )
        data = _flags.flags_for_context(
            user=request.user,
            workspace_id=workspace_id,
            include_sources=include_sources,
            request=request,
        )
        return Response(
            {
                "workspace_id": workspace_id,
                "flags": data,
            },
            status=status.HTTP_200_OK,
        )


class FeatureFlagStatusView(APIView):
    """
    Return evaluation for a single feature flag.

    Path param:
    - key: feature flag key (normalized by the backend)

    Query params:
    - workspace_id: UUID (optional; falls back to user's active workspace)
    - include_source=1: include evaluation source (staff only)

    Membership-gated for the same reason as ``FeatureFlagsView``, and more
    urgently: one flag per request makes this the sharper oracle — a caller
    could walk the flag catalogue a bit at a time against any workspace UUID
    they happened to see in a URL, invite link or Slack deep link.
    """

    permission_classes = [permissions.IsAuthenticated, HasWorkspaceMembership]

    def get(self, request, key: str, format=None):
        _flags = get_feature_flags_provider()
        workspace_id = request.query_params.get("workspace_id") or _flags.resolve_workspace_id_from_request(
            request, view=self
        )
        include_source = bool(request.query_params.get("include_source")) and bool(
            getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)
        )
        result = _flags.evaluate_feature_flag(key, user=request.user, workspace_id=workspace_id, request=request)
        payload = {
            "key": FeatureFlag.normalize_key(key),
            "enabled": result.enabled,
            "workspace_id": workspace_id,
        }
        if include_source:
            payload["source"] = result.source
        return Response(payload, status=status.HTTP_200_OK)


# =============================================================================
# HONEYPOT (SECURITY DECOY) VIEWS
# =============================================================================


class HoneypotLoginView(FormView):
    """
    Renders a fake admin login that records each attempt and always fails.
    """

    template_name = "admin_honeypot/login.html"
    form_class = HoneypotAuthenticationForm
    success_url = reverse_lazy("admin_honeypot:login")

    def form_valid(self, form):
        self._record_attempt(form)
        form.add_error(None, _("Please enter the correct username and password for a staff account."))
        return self.form_invalid(form)

    def _record_attempt(self, form) -> None:
        request = self.request
        username = form.cleaned_data.get("username", "")
        password = form.cleaned_data.get("password", "")
        ip_address = self._client_ip()
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        referer = (request.META.get("HTTP_REFERER") or "")[:255]

        attempt = HoneypotAttempt.objects.create(
            username=username,
            password=password,
            ip_address=ip_address,
            user_agent=user_agent,
            path=request.path,
            method=request.method,
            referer=referer,
        )
        logger.warning(
            "Admin honeypot attempt captured",
            extra={
                "honeypot_attempt_id": attempt.id,
                "username": username,
                "ip": ip_address,
                "user_agent": user_agent,
                "path": request.path,
            },
        )
        messages.error(self.request, _("Your account doesn't have access to this site."))

    def _client_ip(self) -> str | None:
        """Trusted client IP — see ``infrastructure.api.client_ip``.

        The honeypot exists to attribute intrusion attempts to a real origin.
        Reading the caller's own ``X-Forwarded-For`` prefix would let the very
        scanner we are trying to fingerprint dictate the IP we record about it.
        """
        return trusted_client_ip(self.request)


# =============================================================================
# UPLOADS (FILE MANAGEMENT) VIEWS
# =============================================================================


def _scope_files_to_viewer(queryset, user):
    """Narrow a ``File`` queryset to what ``user`` may see.

    Visible == the caller owns the row, OR the row belongs to a workspace the
    caller can access. The document library is a workspace surface (teammates
    share indexed documents), so owner-only would break it; ``workspace_id`` is
    nullable, so workspace-only would strand unattached uploads.

    Workspace access is resolved through the existing
    ``WorkspaceAccessPort`` — the one canonical answer to "which workspaces can
    this viewer see" in this context — rather than a fresh copy of the
    predicate. Anonymous callers get ``none()``.
    """
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return queryset

    from django.db.models import Q

    from components.shared_platform.application.providers.workspace_access_provider import (
        get_workspace_access_adapter,
    )

    workspace_ids = get_workspace_access_adapter().accessible_workspace_ids(user_id=user.id)
    return queryset.filter(Q(owner_id=user.id) | Q(workspace_id__in=workspace_ids))


class FileUploadView(viewsets.ModelViewSet):
    """ViewSet for file upload and management.

    Only ``list`` and ``create`` are routed (see ``uploads_urlpatterns``). The
    collection URL previously also mapped ``put``/``patch``/``delete`` onto the
    inherited ``update``/``destroy``, which call ``get_object()`` — on a route
    with no ``pk`` that raises ``AssertionError`` and returns an unhandled
    **500**, remotely triggerable by any authenticated caller. Those verbs
    already exist, correctly, on the ``<int:pk>/`` detail routes.
    """

    parser_classes = (MultiPartParser, FormParser)
    queryset = File.objects.all()
    serializer_class = FileSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        """Files the caller may see, then the client's optional filters.

        ``GET /upload/`` answered **200 to an anonymous caller** and returned
        every ``File`` row on the deployment. Two things had to be wrong at
        once, and both were: ``IsAuthenticatedOrReadOnly`` permits anonymous
        SAFE_METHODS, and its partner ``IsOwnerOrReadOnly`` is
        ``has_object_permission``-only — a hook DRF never invokes on a list
        route — so it contributed nothing at all.

        The scoping below is the tenant boundary. autosec is single-database
        (ADR 0028): there is no database boundary behind this filter, and
        ``FileSerializer`` ships ``pdf_text`` (the full extracted text of an
        uploaded document) plus a fetchable media URL.

        ``?workspace_id=`` and ``?file_type=`` stay, but strictly as filters
        applied AFTER scoping — they can only ever narrow what the caller may
        already see. Trusting ``?workspace_id=`` to SELECT the tenant is the
        bug, not the feature.
        """
        qs = _scope_files_to_viewer(super().get_queryset(), self.request.user)
        params = self.request.query_params
        workspace_id = (params.get("workspace_id") or "").strip()
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        file_type = (params.get("file_type") or "").strip()
        if file_type:
            kinds = [t.strip() for t in file_type.split(",") if t.strip()]
            if kinds:
                qs = qs.filter(file_type__in=kinds)
        return qs.order_by("-created")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        """Upload a file — delegates through ProcessFileUploadUseCase."""
        from components.shared_platform.application.commands.upload_file_command import (
            UploadFileCommand,
            UploadFileFailure,
        )

        try:
            file = request.FILES.get("file")
            workspace_id = request.data.get("workspace_id")

            if not file:
                return Response(
                    {"message": "No file provided"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not workspace_id:
                return Response(
                    {"message": "workspace_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.utils import timezone

            result = _shared_platform_service.process_file_upload(
                command=UploadFileCommand(
                    owner_id=request.user.id,
                    workspace_id=workspace_id,
                    content_type=file.content_type,
                    # Indexing is opt-in — multipart callers pass index=true
                    # only when the upload's purpose is AI grounding.
                    request_indexing=str(request.data.get("index") or "").lower() in ("true", "1", "yes"),
                    now=timezone.now(),
                ),
                file_obj=file,
                request=request,
            )

            if isinstance(result, UploadFileFailure):
                return Response(
                    {"message": result.message},
                    status=result.status_code,
                )

            payload = {
                "message": (
                    "File uploaded successfully. Processing started."
                    if result.task_id
                    else "File uploaded successfully"
                ),
                "file_id": result.file_id,
                "file_type": result.file_type,
                "processing_status": result.processing_status,
                "file_name": result.file_url,
                "file_url": result.file_url,
                "file_path": result.file_path,
                "created": result.created,
                "workspace_id": result.workspace_id,
                "user_id": result.owner_id,
            }
            if result.task_id:
                payload["task_id"] = result.task_id

            return Response(payload, status=status.HTTP_201_CREATED)

        except RequestDataTooBig:
            return Response(
                {"message": "File size too large"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        except Exception as exc:
            logger.error("Error in file upload: %s", exc, exc_info=True)
            return Response(
                {"message": f"Upload failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@extend_schema_view(
    put=extend_schema(operation_id="upload_detail_update"),
    patch=extend_schema(operation_id="upload_detail_partial_update"),
    delete=extend_schema(operation_id="upload_detail_destroy"),
)
class FileSerializerDetail(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete file details.

    The verbs here are all intended — the frontend GETs and DELETEs by id. The
    defect was the read gate: ``IsAuthenticatedOrReadOnly`` allows anonymous
    SAFE_METHODS and ``IsOwnerOrReadOnly`` returns ``True`` for SAFE_METHODS,
    so the two composed to a fully public GET over ``File.objects.all()``.
    Primary keys are sequential integers, so an anonymous caller could walk
    ``/upload/1..N/`` and read every tenant's document text and media URL.

    ``IsAuthenticated`` replaces the read-only escape hatch;
    ``IsOwnerOrReadOnly`` stays and now actually gates writes. The queryset is
    scoped so a foreign-tenant id 404s rather than 403s — the response must not
    confirm the file exists.
    """

    queryset = File.objects.all()
    serializer_class = FileSerializer
    pagination_class = DefaultPagination
    name = "file-detail"
    permission_classes = (
        permissions.IsAuthenticated,
        IsOwnerOrReadOnly,
    )

    def get_queryset(self):
        return _scope_files_to_viewer(super().get_queryset(), self.request.user)


class PresignedPutUploadView(APIView):
    """Issue a presigned PUT URL so the browser uploads bytes directly
    to S3 instead of streaming them through Django.

    Frontend flow:
        1. ``POST /upload/presigned-put/`` with
           ``{filename, content_type, workspace_id}``.
        2. Server validates membership + MIME and returns
           ``{put_url, key, file_id, expires_in}``.
        3. Browser ``axios.put(put_url, file, { headers: {} })`` —
           bytes go straight to S3, no Django involvement.
        4. ``file_id`` feeds downstream M2M (e.g. ``Recipient.multimedia``);
           ``key`` is what gets stored on ``Recipient.photo_url`` etc.,
           and ``AbsolutePhotoURLField.to_representation`` signs at read
           time.

    Returns 503 when the storage backend is not S3-configured
    (local dev with ``LocalMediaStorage``); the frontend falls back to
    the multipart ``/upload/`` endpoint.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "upload-presigned-put"

    def post(self, request):
        from components.shared_platform.application.commands.request_presigned_upload_command import (
            PresignedUploadFailure,
            RequestPresignedUploadCommand,
        )

        filename = (request.data.get("filename") or "").strip()
        content_type = (request.data.get("content_type") or "").strip()
        workspace_id = (request.data.get("workspace_id") or "").strip()

        if not filename:
            return Response(
                {"message": "filename is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not content_type:
            return Response(
                {"message": "content_type is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not workspace_id:
            return Response(
                {"message": "workspace_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = RequestPresignedUploadCommand(
            owner_id=request.user.id,
            workspace_id=workspace_id,
            filename=filename,
            content_type=content_type,
        )
        result = _shared_platform_service.request_presigned_upload(command)

        if isinstance(result, PresignedUploadFailure):
            return Response(
                {"message": result.message},
                status=result.status_code,
            )

        return Response(
            {
                "put_url": result.put_url,
                "key": result.key,
                "file_id": result.file_id,
                "expires_in": result.expires_in,
            },
            status=status.HTTP_201_CREATED,
        )


class PresignedUploadConfirmView(APIView):
    """Step 2 of the presigned flow: the browser PUT succeeded, so kick
    off async processing (PDF/document → text → embeddings → insights).

    Without this call a presigned upload never processes — the issue
    step allocates the ``File`` row before the bytes exist, so it can't
    dispatch the way the multipart path does. Idempotent; images are a
    successful no-op.
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "upload-presigned-put-confirm"

    def post(self, request):
        from components.shared_platform.application.commands.confirm_presigned_upload_command import (
            ConfirmPresignedUploadCommand,
            ConfirmPresignedUploadFailure,
        )

        raw_file_id = request.data.get("file_id")
        try:
            file_id = int(raw_file_id)
        except (TypeError, ValueError):
            return Response(
                {"message": "file_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = ConfirmPresignedUploadCommand(
            file_id=file_id,
            owner_id=request.user.id,
            # Indexing is opt-in — only uploads with explicit index intent
            # (the AI-grounding uploader) enter the embed pipeline here.
            request_indexing=bool(request.data.get("index")),
        )
        result = _shared_platform_service.confirm_presigned_upload(command)

        if isinstance(result, ConfirmPresignedUploadFailure):
            return Response(
                {"message": result.message},
                status=result.status_code,
            )

        return Response(
            {
                "file_id": result.file_id,
                "file_type": result.file_type,
                "processing_status": result.processing_status,
                "dispatched": result.dispatched,
                "task_id": result.task_id,
                "index_message": result.index_message,
            },
            status=status.HTTP_200_OK,
        )


class DocumentIndexView(APIView):
    """POST /upload/files/<file_id>/index/ — explicitly index a library
    document into the workspace RAG store (opt-in; also the retry path
    for failed indexing).

    Body: { workspace_id } — membership-checked. The use case enforces
    the per-workspace daily quota and the failure circuit-breaker, and
    refuses when embeddings aren't configured. Idempotent for documents
    already queued or indexed.
    """

    permission_classes = (IsOrgOwnerOrMember,)
    name = "upload-document-index"

    def post(self, request, file_id: int):
        from django.utils import timezone

        from components.shared_platform.application.commands.request_document_index_command import (
            RequestDocumentIndexCommand,
            RequestDocumentIndexFailure,
        )

        workspace_id = (request.data.get("workspace_id") or "").strip()
        if not workspace_id:
            return Response(
                {"message": "workspace_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = _shared_platform_service.request_document_index(
            RequestDocumentIndexCommand(
                file_id=file_id,
                requested_by_id=request.user.id,
                workspace_id=workspace_id,
                now=timezone.now(),
            )
        )

        if isinstance(result, RequestDocumentIndexFailure):
            return Response(
                {"message": result.message, "code": result.code},
                status=result.status_code,
            )

        return Response(
            {
                "file_id": result.file_id,
                "processing_status": result.processing_status,
                "dispatched": result.dispatched,
                "task_id": result.task_id,
                "detail": result.detail,
            },
            status=status.HTTP_202_ACCEPTED if result.dispatched else status.HTTP_200_OK,
        )


class TenantLoginBrandView(APIView):
    """Pre-auth login brand for the host serving the request — ``/tenant/login-brand/``.

    The URL identifies the tenant (Host header → tenancy middleware), so the
    login screen on ``faura.auto-sec.ai`` can say "Faura" instead of
    "Auto-Sec" — the wanjala login-brand pattern keyed by host instead of a
    workspace id. Served entirely from the control-plane registry: no tenant
    database is touched and no auth exists yet at this point.

    Security posture: NOT an existence oracle. Unknown subdomains 404 at the
    middleware before this view runs; every non-tenant host (console, bare
    host) gets the byte-identical platform default. Global anon throttle
    applies (deliberately no view-level ``throttle_classes`` — that would
    REPLACE the default anon ceiling, see settings note).
    """

    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        from components.shared_platform.application.providers.tenant_identity_provider import (
            get_tenant_identity_port,
        )

        identity = get_tenant_identity_port().current_login_identity()
        return Response(
            {
                "name": identity.name,
                "subdomain": identity.subdomain,
                "branded": identity.branded,
            }
        )


# Module-level service instance
from components.shared_platform.application.service import SharedPlatformService

_shared_platform_service = SharedPlatformService()
