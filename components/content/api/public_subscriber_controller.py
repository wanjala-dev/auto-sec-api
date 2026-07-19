"""Public, unauthenticated endpoints for the newsletter compliance loop.

Four routes:

- ``POST /content/public/<workspace_id>/subscribe/`` — sponsor profile
  widget + marketing site signup. Rate-limited; always returns 202 to
  avoid email enumeration.
- ``POST /content/public/confirm/<token>/`` — confirmation link in the
  double-opt-in email. Flips the subscriber to active + confirmed.
- ``POST /content/public/unsubscribe/<token>/`` — link in every
  outbound newsletter footer + the destination of the RFC 8058
  ``List-Unsubscribe`` header. Soft-deletes by setting
  ``is_active=False`` (the row stays so the token keeps resolving on
  retries). ``GET`` on the same URL renders a minimal "confirm
  unsubscribe" page for human clicks.
- ``POST /content/email-events/ses/`` — SES SNS bounce + complaint
  webhook. Signature verified against the configured topic ARN before
  any DB write.

All four bypass DRF's default authentication + permission classes —
which mandate ``IsAuthenticated`` for every endpoint by default — via
explicit ``authentication_classes = ()`` + ``permission_classes =
(AllowAny,)`` plus the per-view CSRF exemption needed for the SES
handler since SNS doesn't send CSRF tokens.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from components.content.application.providers.sns_signature_provider import (
    SnsSignatureError,
    get_sns_signature_provider,
)
from infrastructure.api.throttles import (
    NewsletterOpenPixelAnonThrottle,
    NewsletterSubscribeAnonThrottle,
    NewsletterUnsubscribeAnonThrottle,
    SnsWebhookThrottle,
)

logger = logging.getLogger(__name__)


# ───────────────────────── subscribe ─────────────────────────


class PublicSubscribeView(APIView):
    """``POST /content/public/<workspace_id>/subscribe/``.

    Body: ``{"email": "...", "name": "..."}`` — name optional.

    Always 202 unless the body shape is bad (400) or the rate limit is
    hit (429). The response intentionally does NOT distinguish new
    signup from re-subscribe from already-suppressed — exposing those
    states leaks subscriber lists to anyone who can hit the endpoint.

    Double opt-in is gated on ``WorkspacePreference.settings.double_opt_in_enabled``.
    Default is False (single opt-in) for Wanjala's East Africa ICP;
    workspaces with EU touch flip the toggle on their preference page.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (NewsletterSubscribeAnonThrottle,)
    name = "newsletter-public-subscribe"

    def post(self, request, workspace_id: UUID):
        email = (request.data.get("email") or "").strip()
        name = (request.data.get("name") or "").strip()
        if not email or "@" not in email:
            return Response(
                {"detail": "valid email required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        require_confirmation = self._workspace_requires_double_opt_in(workspace_id)

        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        use_case = WritingProvider().build_subscribe_publicly()
        try:
            token, was_new = use_case.execute(
                workspace_id=workspace_id,
                email=email,
                name=name,
                require_confirmation=require_confirmation,
            )
        except Exception:
            logger.exception(
                "public_subscribe_failed workspace_id=%s",
                workspace_id,
            )
            # Even on internal error we still return 202 to avoid leaking
            # enumeration signal. The exception trace is in the logs.
            return Response(status=status.HTTP_202_ACCEPTED)

        # Dispatch confirmation email if double-opt-in is on AND the row
        # is genuinely new (or was previously unconfirmed). The send is
        # async via Celery so the public endpoint stays fast.
        if require_confirmation and was_new:
            from components.content.workers.tasks import (
                send_subscription_confirmation_email,
            )

            send_subscription_confirmation_email.delay(
                workspace_id=str(workspace_id),
                email=email,
                token=str(token),
            )

        return Response(status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _workspace_requires_double_opt_in(workspace_id: UUID) -> bool:
        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        WorkspacePreference = get_workspaces_models_provider().WorkspacePreference

        pref = WorkspacePreference.objects.filter(workspace_id=workspace_id).first()
        if pref is None:
            return False
        settings_dict = pref.settings or {}
        return bool(settings_dict.get("double_opt_in_enabled"))


# ───────────────────────── confirm ─────────────────────────


class PublicConfirmSubscriptionView(APIView):
    """``POST /content/public/confirm/<token>/``.

    Idempotent. Returns 200 on success OR if the token doesn't resolve
    (UX: landing page says "you're subscribed" either way to avoid
    enumeration). Genuine 4xx are reserved for malformed tokens.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (NewsletterUnsubscribeAnonThrottle,)
    name = "newsletter-public-confirm"

    def post(self, request, token: UUID):
        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        use_case = WritingProvider().build_confirm_subscription()
        # Return 200 regardless of whether the token matched — the
        # landing page renders the same "subscription confirmed" UI in
        # both cases. Logged for ops.
        matched = use_case.execute(token=token)
        if not matched:
            logger.info("public_confirm_unknown_token token=%s", token)
        return Response({"status": "ok"})


# ───────────────────────── unsubscribe ─────────────────────────


class PublicUnsubscribeView(APIView):
    """``POST /content/public/unsubscribe/<token>/`` for one-click +
    in-body link unsubscribe; ``GET`` returns a confirm-unsubscribe
    landing page (some inbox clients prefetch GET links, so the GET
    intentionally does NOT mutate).

    POST is idempotent and always 200 — clicking a stale link should
    not leak which tokens are real.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (NewsletterUnsubscribeAnonThrottle,)
    name = "newsletter-public-unsubscribe"

    def post(self, request, token: UUID):
        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        use_case = WritingProvider().build_unsubscribe_subscriber()
        matched = use_case.execute(token=token)
        if not matched:
            logger.info("public_unsubscribe_unknown_token token=%s", token)
        return Response({"status": "unsubscribed"})

    def get(self, request, token: UUID):
        # GET is the human-prefetch-safe path; just acknowledge the
        # token shape without mutating. The FE landing page POSTs back
        # to confirm.
        return Response({"status": "confirm_required", "token": str(token)})


# ───────────────────────── SES SNS webhook ─────────────────────────


@method_decorator(csrf_exempt, name="dispatch")
class SesSnsEventHandlerView(APIView):
    """``POST /content/email-events/ses/``.

    SES posts bounce + complaint notifications to an SNS topic; SNS
    posts JSON here. The handler:

    1. Throttles at ``sns_webhook`` (200/min) so a burst of retries
       can't DDoS the DB.
    2. Verifies the SNS signature against the configured topic ARN.
    3. Handles ``SubscriptionConfirmation`` by GETting the
       ``SubscribeURL`` — that's how SNS topic subscriptions are
       confirmed end-to-end. (We'd usually do this once per
       environment via the AWS console; the auto-handler is here so a
       rebuilt environment self-confirms.)
    4. Handles ``Notification`` with ``notificationType=Bounce`` or
       ``Complaint`` by dispatching the relevant use case.

    SES retries delivery up to ~50 times on transient failure — every
    handler path must be idempotent.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (SnsWebhookThrottle,)
    name = "ses-sns-event-handler"

    def post(self, request: HttpRequest, *args, **kwargs):
        # SNS posts text/plain JSON; DRF won't auto-parse it because the
        # content-type isn't application/json. Always read the raw body.
        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, TypeError):
            logger.warning("sns_invalid_json content_length=%d", len(request.body))
            return Response(
                {"detail": "invalid JSON"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        topic_arn = getattr(settings, "SES_SNS_TOPIC_ARN", "") or None
        try:
            get_sns_signature_provider().verify(payload, expected_topic_arn=topic_arn)
        except SnsSignatureError:
            logger.exception(
                "sns_signature_invalid type=%s topic=%s",
                payload.get("Type"),
                payload.get("TopicArn"),
            )
            return Response(
                {"detail": "signature verification failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message_type = payload.get("Type")
        if message_type == "SubscriptionConfirmation":
            return self._confirm_topic_subscription(payload)
        if message_type == "UnsubscribeConfirmation":
            # Operator removed our SNS subscription via the AWS console;
            # just log and 200.
            logger.info("sns_topic_unsubscribed topic=%s", payload.get("TopicArn"))
            return Response({"status": "ok"})
        if message_type == "Notification":
            return self._handle_notification(payload)

        logger.warning("sns_unknown_type type=%r", message_type)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _confirm_topic_subscription(payload: dict) -> Response:
        import requests

        subscribe_url = payload.get("SubscribeURL")
        if not subscribe_url:
            return Response(
                {"detail": "missing SubscribeURL"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            requests.get(subscribe_url, timeout=5).raise_for_status()
        except requests.RequestException:
            logger.exception("sns_subscription_confirm_failed")
            return Response(
                {"detail": "subscription confirm GET failed"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        logger.info("sns_subscription_confirmed topic=%s", payload.get("TopicArn"))
        return Response({"status": "confirmed"})

    def _handle_notification(self, payload: dict) -> Response:
        # Notification's Message field is itself a JSON string — the SES
        # bounce/complaint body.
        try:
            inner = json.loads(payload.get("Message") or "{}")
        except (ValueError, TypeError):
            logger.warning("sns_notification_invalid_inner_json")
            return Response(
                {"detail": "invalid inner JSON"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notification_type = inner.get("notificationType") or inner.get("eventType")
        if notification_type == "Bounce":
            return self._record_bounce(inner)
        if notification_type == "Complaint":
            return self._record_complaint(inner)
        logger.info(
            "sns_notification_ignored type=%r message_id=%s",
            notification_type,
            payload.get("MessageId"),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _record_bounce(inner: dict) -> Response:
        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        bounce = inner.get("bounce") or {}
        bounce_type = bounce.get("bounceType") or "Undetermined"
        recipients = [
            (r.get("emailAddress") or "").strip()
            for r in bounce.get("bouncedRecipients") or []
            if r.get("emailAddress")
        ]
        if not recipients:
            return Response(status=status.HTTP_204_NO_CONTENT)
        use_case = WritingProvider().build_record_email_bounce()
        newly_suppressed = use_case.execute(
            bounce_type=bounce_type,
            bounced_addresses=recipients,
            source_event=inner,
        )
        logger.info(
            "sns_bounce_recorded type=%s recipients=%d newly_suppressed=%d",
            bounce_type,
            len(recipients),
            newly_suppressed,
        )
        return Response({"newly_suppressed": newly_suppressed})

    @staticmethod
    def _record_complaint(inner: dict) -> Response:
        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        complaint = inner.get("complaint") or {}
        recipients = [
            (r.get("emailAddress") or "").strip()
            for r in complaint.get("complainedRecipients") or []
            if r.get("emailAddress")
        ]
        if not recipients:
            return Response(status=status.HTTP_204_NO_CONTENT)
        use_case = WritingProvider().build_record_email_complaint()
        newly_suppressed = use_case.execute(
            complained_addresses=recipients,
            source_event=inner,
        )
        logger.info(
            "sns_complaint_recorded recipients=%d newly_suppressed=%d",
            len(recipients),
            newly_suppressed,
        )
        return Response({"newly_suppressed": newly_suppressed})


# ───────────────────────── open-tracking pixel ─────────────────────────

# 1×1 transparent GIF — the smallest valid image an email client will
# happily render. Served inline; no file, no storage.
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04"
    b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D"
    b"\x01\x00;"
)


class NewsletterOpenPixelView(APIView):
    """``GET /content/t/o/<token>/`` — the open-tracking pixel (task #25).

    Each emailed recipient's HTML copy embeds this URL with their
    dispatch record's token. A load counts an open: the record's
    open_count/first/last timestamps and the artifact's denormalized
    counters update row-level (no aggregation). Unknown tokens still get
    the pixel — a 404 here would leak which tokens exist and break
    images in forwarded mail; there is nothing for a caller to learn.
    """

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (NewsletterOpenPixelAnonThrottle,)
    name = "newsletter-open-pixel"

    def get(self, request, token: UUID):
        from django.http import HttpResponse

        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        try:
            WritingProvider().build_dispatch_ledger().record_open(open_token=token)
        except Exception:
            # The pixel must NEVER 500 an inbox image loader — count
            # failures are logged and swallowed.
            logger.exception("open_pixel_record_failed token=%s", token)
        response = HttpResponse(_TRANSPARENT_GIF, content_type="image/gif")
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
