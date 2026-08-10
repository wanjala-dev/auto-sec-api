"""Request → RequestContext extraction for the identity controllers.

Single place that knows how to build the audit/session context for a
Django/DRF request. The client IP itself is derived by
``infrastructure.api.client_ip.trusted_client_ip`` — the one canonical rule,
shared with DRF's throttling.

This used to take ``X-Forwarded-For.split(",")[0]`` — the FIRST hop. That entry
is written by the caller, not by our gateway, so anyone could stamp an IP of
their choosing onto their own login events, session records and login-activity
rows. In a security product the auth audit trail is evidence; letting the
subject of the record choose its contents makes it worthless. The trusted hop
is the RIGHTMOST one our proxies appended.
"""

from __future__ import annotations

from components.identity.domain.value_objects.auth_tokens import RequestContext
from infrastructure.api.client_ip import trusted_client_ip


def extract_client_ip(request) -> str | None:
    """Client IP from the rightmost hop this deployment trusts."""
    return trusted_client_ip(request)


def build_request_context(request) -> RequestContext:
    """Build the audit/session RequestContext for this request."""
    return RequestContext(
        ip_address=extract_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "") or "",
    )
